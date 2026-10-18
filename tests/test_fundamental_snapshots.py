from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json

import pandas as pd
import pytest
import requests

from systematic_alpha_lab.data_pipeline.alpha_vantage_rest import (
    AlphaVantageError, AlphaVantageRESTClient, JSONResponse,
)
from systematic_alpha_lab.data_pipeline.fundamental_snapshots import (
    FUNCTIONS, NORMALIZER, ingest_fundamentals, normalize_reports, replay_fundamentals,
)
from systematic_alpha_lab.data_pipeline.ingestion import _filter_date
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

KEY = "synthetic-test-credential"
NOW = pd.Timestamp("2020-08-01T21:00Z")
REQUEST = {"function": "INCOME_STATEMENT", "symbol": "SYNTH"}


def payload(value="100", symbol="SYNTH"):
    return {"symbol": symbol,
            "annualReports": [{"fiscalDateEnding": "2019-12-31", "reportedCurrency": "USD", "netIncome": "400"}],
            "quarterlyReports": [{"fiscalDateEnding": "2020-02-29", "reportedCurrency": "USD", "netIncome": value}]}


def body(value="100"):
    return json.dumps(payload(value)).encode()


class Response:
    def __init__(self, content, status=200):
        self.content = content if isinstance(content, bytes) else json.dumps(content).encode()
        self.status_code = status

    @property
    def text(self):
        return self.content.decode()

    def json(self):
        return json.loads(self.content)


class Session:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def client_with(response):
    client = AlphaVantageRESTClient(KEY)
    client.session = Session(response)
    return client


@pytest.mark.parametrize("response,kind", [
    (Response({"Information": "quota or entitlement notice"}), "provider_notice_or_error"),
    (Response({"Note": "limited"}), "provider_notice_or_error"),
    (Response({"Error Message": "unavailable"}), "provider_notice_or_error"),
    (Response(payload(), 429), "http_429"),
    (Response(payload(), 302), "http_302"),
    (Response(b"not JSON"), "invalid_json"),
    (Response({}), "invalid_or_empty_json"),
    (Response({"symbol": "SYNTH", "echo": KEY}), "credential_echo"),
    (requests.ConnectionError(f"failure at ?apikey={KEY}"), "transport"),
])
def test_provider_failures_never_expose_keys_or_look_like_data(response, kind):
    client = client_with(response)
    with pytest.raises(AlphaVantageError) as caught:
        client.fetch_json_response("INCOME_STATEMENT", {"symbol": "SYNTH"})
    assert caught.value.kind == kind
    assert KEY not in str(caught.value)
    assert len(client.session.calls) == 1


def test_valid_client_retains_exact_bytes_and_does_not_follow_redirects():
    raw = b'{ "symbol": "SYNTH", "quarterlyReports": [] }'
    client = client_with(Response(raw))
    result = client.fetch_json_response("INCOME_STATEMENT", {"symbol": "SYNTH"})
    assert result.body == raw and result.payload["symbol"] == "SYNTH"
    assert client.session.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("parameter", ["apikey", "api_key", "function", "password", "token"])
def test_credentials_and_function_cannot_be_overridden(parameter):
    client = client_with(Response(payload()))
    with pytest.raises(ValueError):
        client.fetch_json("INCOME_STATEMENT", {parameter: "override"})
    assert not client.session.calls


@pytest.mark.parametrize("response", [Response({"Information": "quota"}), Response(b"Information\nlimited\n")])
def test_csv_endpoint_rejects_error_payloads(response):
    with pytest.raises(AlphaVantageError):
        client_with(response).fetch_time_series_csv("TIME_SERIES_DAILY", "SYNTH")


def test_csv_schema_and_legacy_json_api_remain_usable():
    response = Response(b"timestamp,open,high,low,close,volume\n2020-01-02,1,2,1,2,100\n")
    result = client_with(response).fetch_time_series_csv("TIME_SERIES_DAILY", "SYNTH", outputsize="compact")
    assert result.symbol.tolist() == ["SYNTH"]
    assert client_with(Response(payload())).fetch_json("INCOME_STATEMENT")["symbol"] == "SYNTH"


def test_raw_snapshots_are_exact_versioned_and_content_deduplicated(tmp_path):
    store = SnapshotStore(tmp_path)
    first = store.capture("alpha_vantage", REQUEST, body(), observed_at=NOW)
    second = store.capture("alpha_vantage", REQUEST, body(), observed_at=NOW + timedelta(seconds=1))
    third = store.capture("alpha_vantage", REQUEST, body("999"), observed_at=NOW + timedelta(seconds=2))
    assert first["id"] != second["id"]
    assert first["raw_path"] == second["raw_path"] != third["raw_path"]
    assert (tmp_path / first["raw_path"]).read_bytes() == body()
    assert store.read_payload(first)["quarterlyReports"][0]["netIncome"] == "100"
    assert store.latest("alpha_vantage", REQUEST)["id"] == third["id"]
    assert len(list((tmp_path / "raw").rglob("*.json"))) == 2


@pytest.mark.parametrize("issue", ["secret_request", "secret_payload", "provider_error", "naive_time"])
def test_bad_capture_never_creates_a_success_record(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    request, content, observed = dict(REQUEST), body(), NOW
    if issue == "secret_request": request["apikey"] = KEY
    if issue == "secret_payload": content = json.dumps({"nested": {"access_token": KEY}}).encode()
    if issue == "provider_error": content = json.dumps({"Information": "quota"}).encode()
    if issue == "naive_time": observed = "2020-08-01"
    with pytest.raises(ValueError):
        store.capture("alpha_vantage", request, content, observed_at=observed)
    assert store.latest("alpha_vantage", REQUEST) is None


def test_replay_preserves_values_and_unknown_time_units_and_identity(tmp_path):
    store = SnapshotStore(tmp_path)
    record = store.capture("alpha_vantage", REQUEST, body(), observed_at=NOW)
    source = store.read_payload(record)
    before = deepcopy(source)
    tables = normalize_reports(source, record, "INCOME_STATEMENT", "SYNTH")
    assert source == before
    quarter = tables["quarterly"]
    assert quarter.netIncome.tolist() == ["100"]
    assert quarter.available_at.isna().all() and quarter.asset_id.isna().all()
    assert quarter.observed_at.iloc[0] == NOW
    assert quarter.amount_unit_status.eq("unverified").all()
    assert quarter.flow_basis.eq("unverified").all()
    assert not {"fiscal_year", "fiscal_quarter"}.intersection(quarter.columns)
    first = replay_fundamentals(store, record)
    second = replay_fundamentals(store, record)
    assert first == second
    for table in first["tables"].values():
        assert hashlib.sha256((tmp_path / table["path"]).read_bytes()).hexdigest() == table["sha256"]


@pytest.mark.parametrize("issue", ["duplicate", "missing_date", "future", "currency", "symbol", "reserved", "missing_array"])
def test_ambiguous_source_schema_is_quarantined_as_raw_only(tmp_path, issue):
    content = payload()
    if issue == "duplicate": content["quarterlyReports"] *= 2
    if issue == "missing_date": content["quarterlyReports"][0]["fiscalDateEnding"] = ""
    if issue == "future": content["quarterlyReports"][0]["fiscalDateEnding"] = "2021-01-01"
    if issue == "currency": content["quarterlyReports"][0]["reportedCurrency"] = "None"
    if issue == "symbol": content["symbol"] = "OTHER"
    if issue == "reserved": content["quarterlyReports"][0]["available_at"] = "2020-03-01"
    if issue == "missing_array": del content["annualReports"]
    store = SnapshotStore(tmp_path)
    record = store.capture("alpha_vantage", REQUEST, json.dumps(content).encode(), observed_at=NOW)
    with pytest.raises(ValueError):
        replay_fundamentals(store, record)
    assert store.dataset(record["id"], NORMALIZER) is None
    assert store.read_payload(record) == content


@pytest.mark.parametrize("object_type", ["raw", "normalized"])
def test_corruption_is_detected_instead_of_silently_overwritten(tmp_path, object_type):
    store = SnapshotStore(tmp_path)
    record = store.capture("alpha_vantage", REQUEST, body(), observed_at=NOW)
    manifest = replay_fundamentals(store, record)
    path = record["raw_path"] if object_type == "raw" else manifest["tables"]["quarterly"]["path"]
    (tmp_path / path).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        replay_fundamentals(store, record)


class Feed:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on, self.value = [], fail_on, "100"

    def fetch_json_response(self, function, params):
        self.calls.append((function, params))
        if len(self.calls) == self.fail_on:
            raise AlphaVantageError("provider_notice_or_error")
        content = payload(self.value, params["symbol"])
        return JSONResponse(content, json.dumps(content).encode())


def collect(feed, store, **kwargs):
    return ingest_fundamentals(feed, store, symbols=["SYNTH"], min_interval_seconds=0, clock=lambda: NOW, **kwargs)


def test_budget_preflight_happens_before_any_api_call(tmp_path):
    feed = Feed()
    with pytest.raises(ValueError, match="exceeding budget"):
        collect(feed, SnapshotStore(tmp_path), max_requests=2)
    assert feed.calls == []


def test_complete_collection_then_offline_resume_uses_zero_requests(tmp_path):
    feed, store = Feed(), SnapshotStore(tmp_path)
    first = collect(feed, store)
    assert len(feed.calls) == 3 and all(not item["cache_hit"] for item in first)
    resumed = collect(None, store, max_requests=0)
    assert all(item["cache_hit"] for item in resumed)
    assert [item["snapshot_id"] for item in first] == [item["snapshot_id"] for item in resumed]


def test_expired_cache_creates_new_observation_without_replacing_old(tmp_path):
    feed, store = Feed(), SnapshotStore(tmp_path)
    first = collect(feed, store, functions=["INCOME_STATEMENT"])[0]
    feed.value = "999"
    second = ingest_fundamentals(feed, store, symbols=["SYNTH"], functions=["INCOME_STATEMENT"],
                                min_interval_seconds=0, clock=lambda: NOW + timedelta(days=2))[0]
    assert not second["cache_hit"] and first["raw_sha256"] != second["raw_sha256"]
    older = pd.read_parquet(tmp_path / first["tables"]["quarterly"]["path"])
    newer = pd.read_parquet(tmp_path / second["tables"]["quarterly"]["path"])
    assert older.netIncome.iloc[0] == "100" and newer.netIncome.iloc[0] == "999"


def test_provider_failure_stops_without_retry_and_retains_completed_jobs(tmp_path):
    feed, store = Feed(fail_on=2), SnapshotStore(tmp_path)
    with pytest.raises(AlphaVantageError):
        collect(feed, store)
    assert len(feed.calls) == 2
    assert store.latest("alpha_vantage", REQUEST) is not None
    assert store.latest("alpha_vantage", {"function": "BALANCE_SHEET", "symbol": "SYNTH"}) is None


def test_future_cached_observation_cannot_be_used_by_an_earlier_collection_clock(tmp_path):
    store = SnapshotStore(tmp_path)
    store.capture("alpha_vantage", REQUEST, body(), observed_at=NOW + timedelta(days=1))
    feed = Feed()
    with pytest.raises(ValueError, match="later than"):
        collect(feed, store)
    assert not feed.calls


@pytest.mark.parametrize("kwargs", [
    {"symbols": "SYNTH"}, {"symbols": ["../SYNTH"]}, {"functions": ["OTHER"]},
    {"symbols": ["SYNTH", "SYNTH"]}, {"max_requests": True}, {"min_interval_seconds": float("inf")},
    {"min_interval_seconds": -1}, {"cache_max_age": timedelta(days=-1)},
])
def test_invalid_collection_plans_make_no_calls(tmp_path, kwargs):
    feed = Feed()
    options = {"symbols": ["SYNTH"], "min_interval_seconds": 0, "clock": lambda: NOW, **kwargs}
    with pytest.raises(ValueError):
        ingest_fundamentals(feed, SnapshotStore(tmp_path), **options)
    assert not feed.calls


@pytest.mark.parametrize("column", ["date", "timestamp", "datetime", "fiscalDateEnding"])
def test_empty_date_filter_does_not_restore_out_of_range_rows(column):
    frame = pd.DataFrame({column: ["2026-01-01"], "value": [99]})
    before = frame.copy(deep=True)
    result = _filter_date(frame, date(2020, 1, 1), date(2020, 12, 31))
    assert result.empty
    pd.testing.assert_frame_equal(frame, before)
