"""Bounded SEC JSON observations and explicit accession/context staging.

This does not reconstruct original XBRL vintages, fiscal quarters or public
dissemination timestamps. Companyfacts is an aggregate observed at collection.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import time

import pandas as pd
import requests

from .alpha_vantage_rest import JSONResponse
from .snapshot_store import SnapshotStore, utc_time

NORMALIZER = "sec_accession_facts_v1"
DEFAULT_CONCEPTS = (
    ("us-gaap", "Assets"),
    ("us-gaap", "NetIncomeLoss"),
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
)
ACCESSION = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")


class SECError(RuntimeError):
    """Errors omit contact headers, response bodies and transport diagnostics."""

    def __init__(self, kind):
        super().__init__(f"SEC request failed ({kind})")


def sec_request(kind: str, cik: str, *, filename: str | None = None) -> dict:
    if not isinstance(cik, str) or not re.fullmatch(r"[0-9]{1,10}", cik) or int(cik) == 0:
        raise ValueError("Supply a positive CIK of up to ten digits")
    cik = cik.zfill(10)
    if not isinstance(kind, str) or kind not in {"submissions", "companyfacts", "submissions_history"}:
        raise ValueError("Unsupported SEC endpoint")
    result = {"kind": kind, "cik": cik}
    if kind == "submissions_history":
        if not isinstance(filename, str) or not re.fullmatch(rf"CIK{cik}-submissions-[0-9]{{3}}\.json", filename):
            raise ValueError("Invalid SEC history filename for the declared CIK")
        result["filename"] = filename
    elif filename is not None:
        raise ValueError("Only a history request accepts a filename")
    return result


def _canonical(request):
    if not isinstance(request, dict) or not {"kind", "cik"}.issubset(request):
        raise ValueError("Expected an explicit SEC request")
    allowed = {"kind", "cik", "filename"} if request["kind"] == "submissions_history" else {"kind", "cik"}
    if set(request) != allowed:
        raise ValueError("Unexpected SEC request fields")
    return sec_request(request["kind"], request["cik"], filename=request.get("filename"))


def _validate_payload(payload, request):
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Expected a nonempty SEC JSON object")
    kind = request["kind"]
    if kind != "submissions_history":
        cik = payload.get("cik")
        if isinstance(cik, bool) or not isinstance(cik, (str, int)) or str(cik).zfill(10) != request["cik"]:
            raise ValueError("SEC response CIK differs from request")
    if kind == "companyfacts" and not isinstance(payload.get("facts"), dict):
        raise ValueError("SEC companyfacts schema missing")
    if kind == "submissions" and (not isinstance(payload.get("filings"), dict) or not isinstance(
        payload["filings"].get("recent"), dict
    )):
        raise ValueError("SEC submission schema missing")
    if kind == "submissions_history" and not isinstance(payload.get("accessionNumber"), list):
        raise ValueError("SEC history schema missing")


class SECClient:
    """Serial single-process client; caller supplies an authorized contact header.

    No key, retry, redirect or arbitrary URL. Separate processes must coordinate
    their aggregate request rate outside this reference client.
    """

    def __init__(self, user_agent: str, *, min_interval_seconds: float = 0.5):
        contact = re.search(r"[A-Za-z0-9_.+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", user_agent) if isinstance(
            user_agent, str
        ) else None
        if not isinstance(user_agent, str) or not re.fullmatch(r"[\x20-\x7e]{8,200}", user_agent) or contact is None or not (
            user_agent[:contact.start()].strip(" <")
        ):
            raise ValueError("SEC_USER_AGENT must identify the organization and an authorized contact email")
        if isinstance(min_interval_seconds, bool) or not isinstance(min_interval_seconds, (int, float)) or not (
            0.2 <= min_interval_seconds <= 60
        ):
            raise ValueError("SEC interval must be between 0.2 and 60 seconds")
        self._user_agent = user_agent
        self._contact_email = contact.group()
        self._interval = min_interval_seconds
        self._last_call = None
        self.session = requests.Session()

    def fetch_json_response(self, request: dict) -> JSONResponse:
        request = _canonical(request)
        kind, cik = request["kind"], request["cik"]
        if kind == "companyfacts":
            path = f"api/xbrl/companyfacts/CIK{cik}.json"
        else:
            path = "submissions/" + request.get("filename", f"CIK{cik}.json")
        if self._last_call is not None:
            time.sleep(max(0.0, self._interval - (time.monotonic() - self._last_call)))
        self._last_call = time.monotonic()
        try:
            response = self.session.get(
                "https://data.sec.gov/" + path,
                headers={"User-Agent": self._user_agent, "Accept": "application/json"},
                timeout=(10, 60), allow_redirects=False,
            )
        except requests.RequestException:
            raise SECError("transport") from None
        if response.status_code != 200:
            raise SECError(f"http_{response.status_code}")
        # Neither the declared identity nor an echoed email belongs in raw data.
        if self._contact_email.encode() in response.content:
            raise SECError("contact_echo")
        try:
            payload = response.json()
            _validate_payload(payload, request)
        except (ValueError, TypeError, AttributeError):
            raise SECError("invalid_source_schema") from None
        return JSONResponse(payload, response.content)


def collect_sec_snapshots(
    client, store: SnapshotStore, *, plan: list[dict], max_requests: int = 2,
    cache_max_age: timedelta = timedelta(hours=24), clock=utc_time,
) -> list[dict]:
    """Preflight the entire explicit plan; offline mode constructs no client."""
    if not isinstance(plan, (list, tuple)) or not plan:
        raise ValueError("Declare a nonempty SEC collection plan")
    if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests < 0:
        raise ValueError("Invalid SEC request budget")
    if not isinstance(cache_max_age, timedelta) or cache_max_age < timedelta(0):
        raise ValueError("Invalid SEC cache age")
    requests_ = [_canonical(request) for request in plan]
    if len({json.dumps(request, sort_keys=True) for request in requests_}) != len(requests_):
        raise ValueError("Duplicate SEC requests")
    now, jobs = utc_time(clock()), []
    for request in requests_:
        record = store.latest("sec", request)
        if record is not None:
            age = now - utc_time(record["observed_at"])
            if age < timedelta(0):
                raise ValueError("SEC cache observation is in the future")
            if age > cache_max_age:
                record = None
        jobs.append((request, record))
    required = sum(record is None for _, record in jobs)
    if required > max_requests or (required and client is None):
        raise ValueError("SEC budget/cache preflight failed; no calls made")
    receipts = []
    for request, record in jobs:
        cached = record is not None
        if not cached:
            response = client.fetch_json_response(request)
            _validate_payload(json.loads(response.body), request)
            record = store.capture("sec", request, response.body, observed_at=clock())
        else:
            _validate_payload(store.read_payload(record), request)
        receipts.append({"request": request, "cache_hit": cached, "record": record})
    return receipts


def _date(value, *, optional=False):
    if optional and value in (None, ""):
        return pd.NaT
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Expected an ISO financial date")
    return pd.Timestamp(value, tz="UTC")


def _filings(payloads):
    rows = []
    required = {"accessionNumber", "filingDate", "reportDate", "form"}
    for payload in payloads:
        columns = payload["filings"]["recent"] if "filings" in payload else payload
        if not required.issubset(columns) or any(not isinstance(v, list) for v in columns.values()):
            raise ValueError("SEC filing history must use column arrays")
        lengths = {len(v) for v in columns.values()}
        if len(lengths) != 1:
            raise ValueError("SEC filing history columns have unequal lengths")
        for i in range(len(columns["accessionNumber"])):
            row = {k: v[i] for k, v in columns.items()}
            if not isinstance(row["accessionNumber"], str) or not ACCESSION.fullmatch(row["accessionNumber"]):
                raise ValueError("Invalid SEC accession")
            accepted = row.get("acceptanceDateTime")
            stamp = pd.Timestamp(accepted) if accepted else pd.NaT
            explicit_zone = not pd.isna(stamp) and stamp.tzinfo is not None
            rows.append({
                "accession": row["accessionNumber"], "filing_date": _date(row["filingDate"]),
                "report_date": _date(row["reportDate"], optional=True), "form": row["form"],
                "accepted_at_source": accepted,
                "accepted_at_utc": stamp.tz_convert("UTC") if explicit_zone else pd.NaT,
                "acceptance_time_basis": "source_offset" if explicit_zone else "timezone_or_time_missing",
            })
    frame = pd.DataFrame(rows, columns=["accession", "filing_date", "report_date", "form",
                                       "accepted_at_source", "accepted_at_utc", "acceptance_time_basis"])
    if frame.accession.duplicated().any():
        raise ValueError("Overlapping or conflicting accession metadata; resolve sources explicitly")
    frame["accepted_at_utc"] = pd.to_datetime(frame.accepted_at_utc, utc=True)
    return frame


def replay_sec_facts(
    store: SnapshotStore, facts_record: dict, submissions_record: dict, *,
    concepts=DEFAULT_CONCEPTS, history_records=(),
) -> dict:
    """Preserve selected facts and exact accession joins, without choosing a vintage.

    Filing fy/fp refer to the source filing, not necessarily the fact period.
    Acceptance is metadata, never silently promoted to historical available_at.
    """
    records = [facts_record, submissions_record, *history_records]
    requests_ = [json.loads(record["request_json"]) for record in records]
    for record, request in zip(records, requests_):
        if record["provider"] != "sec" or _canonical(request) != request:
            raise ValueError("Only canonical SEC snapshot records are accepted")
    if [request["kind"] for request in requests_[:2]] != ["companyfacts", "submissions"] or any(
        r["kind"] != "submissions_history" for r in requests_[2:]
    ) or len({r["cik"] for r in requests_}) != 1:
        raise ValueError("Require one company's facts, submissions and optional history")
    if not isinstance(concepts, (list, tuple)) or not concepts or any(
        not isinstance(pair, (tuple, list)) or len(pair) != 2 or any(
            not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", item) for item in pair
        ) for pair in concepts
    ) or len({tuple(pair) for pair in concepts}) != len(concepts):
        raise ValueError("Declare unique namespace/tag pairs")
    payloads = [store.read_payload(record) for record in records]
    for payload, request in zip(payloads, requests_):
        _validate_payload(payload, request)
    files = payloads[1]["filings"].get("files", [])
    if not isinstance(files, list) or any(not isinstance(entry, dict) or not isinstance(
        entry.get("name"), str
    ) for entry in files):
        raise ValueError("Invalid SEC historical filing references")
    declared_history = {entry["name"] for entry in files}
    if any(request["filename"] not in declared_history for request in requests_[2:]):
        raise ValueError("History file was not listed in the submissions snapshot")
    provenance = {
        "normalizer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_snapshots": [{k: r[k] for k in ("id", "raw_sha256", "observed_at")} for r in records],
        "concepts": [list(pair) for pair in concepts],
    }
    # The derived dataset depends on all observations and the explicit concept set.
    suffix = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:20]
    version = f"{NORMALIZER}_{suffix}"
    existing = store.dataset(facts_record["id"], version)
    if existing is not None:
        return existing
    filings = _filings(payloads[1:])
    rows = []
    for namespace, tag in concepts:
        concept = payloads[0]["facts"].get(namespace, {}).get(tag)
        if not isinstance(concept, dict) or not isinstance(concept.get("units"), dict):
            raise ValueError("Requested SEC concept missing; do not substitute another definition")
        for unit, facts in concept["units"].items():
            if not isinstance(unit, str) or not unit or not isinstance(facts, list):
                raise ValueError("Invalid SEC concept unit array")
            for fact in facts:
                if not isinstance(fact, dict) or not {"val", "end", "accn", "filed", "form"}.issubset(fact):
                    raise ValueError("Incomplete SEC fact")
                if not isinstance(fact["accn"], str) or not ACCESSION.fullmatch(fact["accn"]):
                    raise ValueError("Invalid fact accession")
                value = fact["val"]
                try:
                    numeric = Decimal(str(value))
                except InvalidOperation:
                    raise ValueError("Invalid SEC numeric value") from None
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not numeric.is_finite():
                    raise ValueError("Invalid SEC numeric value")
                start, end = _date(fact.get("start"), optional=True), _date(fact["end"])
                if not pd.isna(start) and start > end:
                    raise ValueError("Fact duration starts after period end")
                rows.append({
                    "cik": requests_[0]["cik"], "namespace": namespace, "tag": tag, "unit": unit,
                    "value_text": str(value), "period_start": start, "period_end": end,
                    "context_kind": "instant" if pd.isna(start) else "duration",
                    "duration_days": None if pd.isna(start) else (end - start).days + 1,
                    "accession": fact["accn"], "filed": _date(fact["filed"]), "form": fact["form"],
                    "source_fy": fact.get("fy"), "source_fp": fact.get("fp"), "source_frame": fact.get("frame"),
                })
    if not rows:
        raise ValueError("No selected SEC facts")
    frame = pd.DataFrame(rows)
    frame["period_start"] = pd.to_datetime(frame.period_start, utc=True)
    frame["duration_days"] = frame.duration_days.astype("Int64")
    frame = frame.merge(filings, on="accession", how="left", suffixes=("", "_submission"),
                                     validate="many_to_one", indicator=True)
    matched = frame["_merge"].eq("both")
    if (matched & (frame.filed.ne(frame.filing_date) | frame.form.ne(frame.form_submission))).any():
        raise ValueError("Fact metadata conflicts with exact-accession submission")
    frame["filing_metadata_status"] = matched.map({True: "matched_accession", False: "missing_history"})
    frame = frame.drop(columns=["_merge"])
    frame["observed_at"] = utc_time(facts_record["observed_at"])
    frame["available_at"] = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    frame["availability_basis"] = "public_dissemination_not_verified"
    return store.publish_tables(facts_record, version, {"facts": frame, "filings": filings}, provenance=provenance)


def select_sec_context(facts: pd.DataFrame, *, accession: str, namespace: str, tag: str,
                       unit: str, period_end: str, period_start: str | None = None) -> pd.Series:
    """Select exactly one accession/unit/duration; ambiguity is an error."""
    start, end = _date(period_start, optional=True), _date(period_end)
    mask = facts.accession.eq(accession) & facts.namespace.eq(namespace) & facts.tag.eq(tag) & facts.unit.eq(unit)
    mask &= facts.period_end.eq(end)
    mask &= facts.period_start.isna() if pd.isna(start) else facts.period_start.eq(start)
    result = facts.loc[mask]
    if len(result) != 1:
        raise ValueError("Exact SEC context is missing or ambiguous")
    return result.iloc[0].copy()
