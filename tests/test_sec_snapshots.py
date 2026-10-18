"""Synthetic source contracts; no SEC network or real company data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import pytest
import requests

from systematic_alpha_lab.data_pipeline.alpha_vantage_rest import JSONResponse
from systematic_alpha_lab.data_pipeline.sec_snapshots import (
    DEFAULT_CONCEPTS, SECClient, SECError, collect_sec_snapshots, replay_sec_facts,
    sec_request, select_sec_context,
)
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

CIK = "0000000042"
ACC = "0000000042-20-000001"
OLD = "0000000042-20-000000"
NOW = datetime(2020, 8, 1, tzinfo=timezone.utc)
CONTACT = "Synthetic Research test@example.invalid"
PLAN = [sec_request(kind, CIK) for kind in ("submissions", "companyfacts")]


def filings():
    return {"cik": CIK, "filings": {"recent": {
        "accessionNumber": [ACC], "filingDate": ["2020-07-30"],
        "reportDate": ["2020-06-30"], "form": ["10-Q"],
        "acceptanceDateTime": ["2020-07-30T17:00:00-04:00"],
    }, "files": [{"name": f"CIK{CIK}-submissions-001.json"}]}}


def facts():
    base = {"accn": ACC, "filed": "2020-07-30", "form": "10-Q", "fy": 2020,
            "fp": "Q2", "end": "2020-06-30"}
    return {"cik": 42, "entityName": "Explicitly Synthetic Entity", "facts": {"us-gaap": {
        "Assets": {"units": {"USD": [{**base, "val": 1000}]}},
        "NetIncomeLoss": {"units": {"USD": [
            {**base, "start": "2020-04-01", "val": 30, "frame": "CY2020Q2"},
            {**base, "start": "2020-01-01", "val": 50},
        ]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            {**base, "start": "2020-01-01", "val": 60},
        ]}},
    }}}


def capture_pair(store, fact_payload=None, filing_payload=None):
    submission = store.capture("sec", PLAN[0], json.dumps(filing_payload or filings()).encode(), observed_at=NOW)
    fact = store.capture("sec", PLAN[1], json.dumps(fact_payload or facts()).encode(), observed_at=NOW)
    return fact, submission


def table(store, manifest, name="facts"):
    return pd.read_parquet(store.root / manifest["tables"][name]["path"])


class Response:
    def __init__(self, payload, status=200):
        self.content = json.dumps(payload).encode()
        self.status_code = status

    def json(self):
        return json.loads(self.content)


class Session:
    def __init__(self, result):
        self.result, self.calls = result, []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def client(result):
    result_client = SECClient(CONTACT)
    result_client.session = Session(result)
    return result_client


def test_client_uses_only_official_path_and_explicit_contact():
    source = client(Response(filings()))
    result = source.fetch_json_response(PLAN[0])
    args, kwargs = source.session.calls[0]
    assert args == (f"https://data.sec.gov/submissions/CIK{CIK}.json",)
    assert kwargs["headers"]["User-Agent"] == CONTACT
    assert kwargs["allow_redirects"] is False and kwargs["timeout"] == (10, 60)
    assert result.payload == filings()


@pytest.mark.parametrize("agent", [None, "", "Research", "Research\ncontact@example.invalid"])
def test_contact_is_never_invented(agent):
    with pytest.raises(ValueError):
        SECClient(agent)


@pytest.mark.parametrize("interval", [0, .1, -1, float("nan"), float("inf"), True])
def test_client_enforces_a_conservative_rate_floor(interval):
    with pytest.raises(ValueError):
        SECClient(CONTACT, min_interval_seconds=interval)


def test_client_paces_consecutive_attempts(monkeypatch):
    module = "systematic_alpha_lab.data_pipeline.sec_snapshots.time"
    monkeypatch.setattr(module + ".monotonic", lambda: 100.0)
    waits = []
    monkeypatch.setattr(module + ".sleep", waits.append)
    source = client(Response(filings()))
    source.fetch_json_response(PLAN[0])
    source.fetch_json_response(PLAN[0])
    assert waits == [.5]


@pytest.mark.parametrize("result", [
    Response({"message": CONTACT}, 403), Response({}, 302), Response({"error": CONTACT}),
    Response({**filings(), "contact": "test@example.invalid"}),
    requests.ConnectionError(CONTACT), Response({**filings(), "cik": "43"}),
])
def test_errors_never_expose_contact_or_enter_the_cache(result):
    source = client(result)
    with pytest.raises(SECError) as caught:
        source.fetch_json_response(PLAN[0])
    assert "test@example.invalid" not in str(caught.value)
    assert caught.value.__suppress_context__ or "http_" in str(caught.value) or "contact_echo" in str(caught.value)
    assert len(source.session.calls) == 1


@pytest.mark.parametrize("plan_request", [
    {"kind": "submissions", "cik": "../42"}, {"kind": "other", "cik": "42"},
    {"kind": "submissions", "cik": "0"}, {"kind": "submissions", "cik": "42", "url": "https://other.invalid"},
    {"kind": "submissions_history", "cik": "42", "filename": "../../data.json"},
    {"kind": "submissions_history", "cik": "42", "filename": "CIK0000000043-submissions-001.json"},
])
def test_paths_cannot_be_overridden(plan_request, tmp_path):
    source = client(Response(filings()))
    with pytest.raises(ValueError):
        collect_sec_snapshots(source, SnapshotStore(tmp_path), plan=[plan_request], clock=lambda: NOW)
    assert not source.session.calls


def test_budget_preflight_cache_replay_and_expiry(tmp_path):
    store = SnapshotStore(tmp_path)

    class FixtureClient:
        def __init__(self): self.calls = []
        def fetch_json_response(self, request):
            self.calls.append(request)
            payload = filings() if request["kind"] == "submissions" else facts()
            return JSONResponse(payload, json.dumps(payload).encode())

    source = FixtureClient()
    with pytest.raises(ValueError, match="no calls made"):
        collect_sec_snapshots(source, store, plan=PLAN, max_requests=1, clock=lambda: NOW)
    assert source.calls == []
    receipts = collect_sec_snapshots(source, store, plan=PLAN, clock=lambda: NOW)
    assert len(source.calls) == 2 and not any(r["cache_hit"] for r in receipts)
    cached = collect_sec_snapshots(None, store, plan=PLAN, max_requests=0, clock=lambda: NOW)
    assert all(r["cache_hit"] for r in cached)
    assert [r["record"]["id"] for r in cached] == [r["record"]["id"] for r in receipts]
    with pytest.raises(ValueError, match="no calls made"):
        collect_sec_snapshots(None, store, plan=PLAN, max_requests=0, clock=lambda: NOW + timedelta(days=2))
    refreshed = collect_sec_snapshots(source, store, plan=PLAN, clock=lambda: NOW + timedelta(days=2))
    assert len(source.calls) == 4
    assert refreshed[0]["record"]["id"] != receipts[0]["record"]["id"]
    assert refreshed[0]["record"]["raw_path"] == receipts[0]["record"]["raw_path"]


def test_offline_missing_future_and_corrupted_cache_fail(tmp_path):
    store = SnapshotStore(tmp_path)
    with pytest.raises(ValueError):
        collect_sec_snapshots(None, store, plan=PLAN, clock=lambda: NOW)
    fact, submission = capture_pair(store)
    with pytest.raises(ValueError, match="future"):
        collect_sec_snapshots(None, store, plan=PLAN, clock=lambda: NOW - timedelta(days=1))
    (store.root / fact["raw_path"]).write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        collect_sec_snapshots(None, store, plan=PLAN, clock=lambda: NOW)


@pytest.mark.parametrize("plan,budget,age", [
    ([], 2, timedelta(days=1)), (PLAN + PLAN, 2, timedelta(days=1)),
    (PLAN, True, timedelta(days=1)), (PLAN, -1, timedelta(days=1)),
    (PLAN, 2, timedelta(days=-1)),
])
def test_invalid_collection_plan_is_rejected(tmp_path, plan, budget, age):
    with pytest.raises(ValueError):
        collect_sec_snapshots(None, SnapshotStore(tmp_path), plan=plan, max_requests=budget,
                              cache_max_age=age, clock=lambda: NOW)


def test_accession_contexts_units_and_unknown_availability_are_preserved(tmp_path):
    store = SnapshotStore(tmp_path)
    fact, submission = capture_pair(store)
    before = store.read_payload(fact)
    manifest = replay_sec_facts(store, fact, submission)
    frame = table(store, manifest)
    assert len(frame) == 4 and frame.available_at.isna().all()
    assert frame.filing_metadata_status.eq("matched_accession").all()
    assert frame.accepted_at_utc.eq(pd.Timestamp("2020-07-30T21:00:00Z")).all()
    assert frame.availability_basis.eq("public_dissemination_not_verified").all()
    assert frame.source_fy.eq(2020).all() and frame.source_fp.eq("Q2").all()
    assert not {"fiscal_year", "fiscal_quarter", "security_id", "asset_id"}.intersection(frame.columns)
    assert store.read_payload(fact) == before
    assert replay_sec_facts(store, fact, submission) == manifest
    quarter = select_sec_context(frame, accession=ACC, namespace="us-gaap", tag="NetIncomeLoss",
                                 unit="USD", period_start="2020-04-01", period_end="2020-06-30")
    assert quarter.value_text == "30" and quarter.duration_days == 91
    cfo = select_sec_context(frame, accession=ACC, namespace="us-gaap",
                             tag="NetCashProvidedByUsedInOperatingActivities", unit="USD",
                             period_start="2020-01-01", period_end="2020-06-30")
    assert cfo.duration_days == 182 and cfo.value_text == "60"
    # A six-month source amount must not be relabelled as a three-month flow.
    with pytest.raises(ValueError):
        select_sec_context(frame, accession=ACC, namespace="us-gaap", tag=cfo.tag,
                           unit="USD", period_start="2020-04-01", period_end="2020-06-30")


def test_naive_acceptance_is_not_assumed_to_be_utc(tmp_path):
    store = SnapshotStore(tmp_path)
    payload = filings()
    payload["filings"]["recent"]["acceptanceDateTime"] = ["2020-07-30T17:00:00"]
    fact, submission = capture_pair(store, filing_payload=payload)
    frame = table(store, replay_sec_facts(store, fact, submission))
    assert frame.accepted_at_utc.isna().all() and frame.available_at.isna().all()
    assert frame.accepted_at_source.eq("2020-07-30T17:00:00").all()


def test_missing_history_is_explicit_and_listed_history_resolves_it(tmp_path):
    store = SnapshotStore(tmp_path)
    payload = facts()
    payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["accn"] = OLD
    fact, submission = capture_pair(store, fact_payload=payload)
    first = replay_sec_facts(store, fact, submission)
    frame = table(store, first)
    assert frame.loc[frame.tag.eq("Assets"), "filing_metadata_status"].tolist() == ["missing_history"]
    history = deepcopy(filings()["filings"]["recent"])
    history["accessionNumber"] = [OLD]
    request = sec_request("submissions_history", CIK, filename=f"CIK{CIK}-submissions-001.json")
    history_record = store.capture("sec", request, json.dumps(history).encode(), observed_at=NOW)
    second = replay_sec_facts(store, fact, submission, history_records=[history_record])
    assert second["normalizer"] != first["normalizer"]
    assert table(store, second).filing_metadata_status.eq("matched_accession").all()
    assert len(second["provenance"]["input_snapshots"]) == 3
    (store.root / history_record["raw_path"]).write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        replay_sec_facts(store, fact, submission, history_records=[history_record])


@pytest.mark.parametrize("issue", ["overlap", "unlisted", "wrong_cik"])
def test_bad_history_is_not_silently_joined(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    fact, submission = capture_pair(store)
    filename = f"CIK{CIK}-submissions-{'002' if issue == 'unlisted' else '001'}.json"
    request = sec_request("submissions_history", "43" if issue == "wrong_cik" else CIK,
                          filename=filename.replace(CIK, "0000000043") if issue == "wrong_cik" else filename)
    history = store.capture("sec", request, json.dumps(filings()["filings"]["recent"]).encode(), observed_at=NOW)
    with pytest.raises(ValueError):
        replay_sec_facts(store, fact, submission, history_records=[history])


@pytest.mark.parametrize("issue", ["filed", "form", "column_length", "duplicate_accession"])
def test_conflicting_filing_metadata_is_quarantined(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    payload = filings()
    columns = payload["filings"]["recent"]
    if issue == "filed": columns["filingDate"] = ["2020-07-31"]
    if issue == "form": columns["form"] = ["10-K"]
    if issue == "column_length": columns["form"].append("10-K")
    if issue == "duplicate_accession":
        for values in columns.values(): values.extend(values[:])
    fact, submission = capture_pair(store, filing_payload=payload)
    with pytest.raises(ValueError):
        replay_sec_facts(store, fact, submission)


@pytest.mark.parametrize("issue", ["missing_tag", "missing_value", "nan", "bool", "duration", "accn"])
def test_bad_facts_are_not_certified(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    payload = facts()
    fact = payload["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"][0]
    if issue == "missing_tag": del payload["facts"]["us-gaap"]["Assets"]
    if issue == "missing_value": del fact["val"]
    if issue == "nan": fact["val"] = float("nan")
    if issue == "bool": fact["val"] = True
    if issue == "duration": fact["start"] = "2020-07-01"
    if issue == "accn": fact["accn"] = "bad"
    fact_record, submission = capture_pair(store, fact_payload=payload)
    with pytest.raises(ValueError):
        replay_sec_facts(store, fact_record, submission)
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0


def test_exact_context_does_not_hide_duplicates_or_cross_units(tmp_path):
    store = SnapshotStore(tmp_path)
    payload = facts()
    amounts = payload["facts"]["us-gaap"]["Assets"]["units"]
    amounts["USD"].append(deepcopy(amounts["USD"][0]))
    amounts["EUR"] = [{**amounts["USD"][0], "val": 800}]
    fact, submission = capture_pair(store, fact_payload=payload)
    frame = table(store, replay_sec_facts(store, fact, submission))
    with pytest.raises(ValueError, match="ambiguous"):
        select_sec_context(frame, accession=ACC, namespace="us-gaap", tag="Assets",
                           unit="USD", period_end="2020-06-30")
    assert select_sec_context(frame, accession=ACC, namespace="us-gaap", tag="Assets",
                              unit="EUR", period_end="2020-06-30").value_text == "800"


@pytest.mark.parametrize("concepts", [[], [("us-gaap", "Assets")] * 2, [("us-gaap", "../Assets")]])
def test_explicit_concept_contract(tmp_path, concepts):
    store = SnapshotStore(tmp_path)
    fact, submission = capture_pair(store)
    with pytest.raises(ValueError):
        replay_sec_facts(store, fact, submission, concepts=concepts)


@pytest.mark.parametrize("field", ["api_key", "access_token", "AWS_SECRET_ACCESS_KEY", "password", "Authorization"])
def test_raw_payload_credentials_are_still_rejected(tmp_path, field):
    store = SnapshotStore(tmp_path)
    with pytest.raises(ValueError, match="Credentials"):
        store.capture("sec", PLAN[1], json.dumps({"nested": {field: "sensitive"}}).encode(), observed_at=NOW)


def test_financial_taxonomy_names_are_not_mistaken_for_credentials(tmp_path):
    store = SnapshotStore(tmp_path)
    payload = {"facts": {"ifrs-full": {"KeyManagementPersonnelCompensation": {"units": {"USD": []}}}}}
    record = store.capture("sec", PLAN[1], json.dumps(payload).encode(), observed_at=NOW)
    assert store.read_payload(record) == payload
    with pytest.raises(ValueError):
        SnapshotStore.request_id("sec", {**PLAN[1], "contact_user_agent": CONTACT, "api_key": "sensitive"})
