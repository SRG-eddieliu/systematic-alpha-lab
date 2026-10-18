"""Bounded Alpha Vantage collection with replayable, source-aware snapshots."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import time

import pandas as pd

from .snapshot_store import SnapshotStore, utc_time

FUNCTIONS = ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW")
NORMALIZER = "av_fundamentals_v1"


def normalize_reports(payload: dict, record: dict, function: str, symbol: str) -> dict[str, pd.DataFrame]:
    """Preserve provider amounts; do not infer fiscal quarters, units or YTD basis."""
    if function not in FUNCTIONS or payload.get("symbol") != symbol:
        raise ValueError("Unexpected fundamental source/function/symbol")
    observed_at = pd.Timestamp(utc_time(record["observed_at"]))
    tables = {}
    metadata = {"provider", "source_function", "symbol", "period_type", "period_end", "currency",
                "observed_at", "available_at", "availability_basis", "snapshot_id", "normalizer",
                "asset_id", "identifier_basis", "amount_unit_status", "flow_basis"}
    for key, period_type in (("annualReports", "annual"), ("quarterlyReports", "quarterly")):
        reports = payload.get(key)
        if not isinstance(reports, list):
            raise ValueError("Expected annualReports and quarterlyReports arrays")
        if not reports:
            continue
        if any(not isinstance(row, dict) or metadata.intersection(row) for row in reports):
            raise ValueError("Unexpected report shape or reserved metadata fields")
        frame = pd.DataFrame(reports)
        if not {"fiscalDateEnding", "reportedCurrency"}.issubset(frame):
            raise ValueError("Fundamental report lacks period/currency")
        frame["period_end"] = pd.to_datetime(frame.fiscalDateEnding, utc=True, errors="raise")
        if frame.period_end.isna().any() or frame.period_end.duplicated().any():
            raise ValueError("Missing or duplicate report periods; do not deduplicate source versions")
        if (frame.period_end > observed_at.normalize()).any():
            raise ValueError("Source financial periods exceed the observation date")
        currency = frame.reportedCurrency.astype("string")
        if currency.isna().any() or not currency.str.fullmatch(r"[A-Z]{3}").all():
            raise ValueError("Missing or unsupported reported currency")
        frame = frame.assign(
            provider="alpha_vantage", source_function=function, symbol=symbol, period_type=period_type,
            currency=currency, observed_at=observed_at, snapshot_id=record["id"], normalizer=NORMALIZER,
            availability_basis="not_supplied", identifier_basis="provider_symbol_unmapped",
            amount_unit_status="unverified", flow_basis="stock" if function == "BALANCE_SHEET" else "unverified",
        )
        frame["available_at"] = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
        frame["asset_id"] = pd.Series(pd.NA, index=frame.index, dtype="string")
        # Keep original amount fields verbatim; research conversion is a separate contract.
        tables[period_type] = frame.sort_values("period_end").reset_index(drop=True)
    if not tables:
        raise ValueError("No reports returned")
    return tables


def replay_fundamentals(store: SnapshotStore, record: dict) -> dict:
    payload = store.read_payload(record)
    signature = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    existing = store.dataset(record["id"], NORMALIZER)
    if existing is not None:
        if existing["provenance"].get("normalizer_source_sha256") != signature:
            raise ValueError("Normalizer source changed; use a new normalizer version")
        return existing
    request = json.loads(record["request_json"])
    tables = normalize_reports(payload, record, request["function"], request["symbol"])
    return store.publish_tables(record, NORMALIZER, tables, provenance={"normalizer_source_sha256": signature})


def ingest_fundamentals(
    client, store: SnapshotStore, *, symbols: list[str], functions=FUNCTIONS,
    max_requests: int = 3, cache_max_age: timedelta = timedelta(hours=24),
    min_interval_seconds: float = 15.0, clock=utc_time, sleep=time.sleep,
) -> list[dict]:
    """Preflight the whole call budget; stop on errors, without retry/key rotation.

    client=None permits offline replay of fresh cached snapshots only. This path
    never constructs a historical universe or requires WRDS credentials.
    """
    if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests < 0:
        raise ValueError("max_requests must be a nonnegative integer")
    if not isinstance(cache_max_age, timedelta) or cache_max_age < timedelta(0):
        raise ValueError("cache_max_age must be a nonnegative timedelta")
    if isinstance(min_interval_seconds, bool) or not isinstance(min_interval_seconds, (int, float)) or not (
        math.isfinite(min_interval_seconds) and 0 <= min_interval_seconds <= 60
    ):
        raise ValueError("min_interval_seconds must be between 0 and 60")
    if not isinstance(symbols, (list, tuple)) or not isinstance(functions, (list, tuple)) or not symbols or not functions:
        raise ValueError("Declare nonempty unique symbols and functions")
    if any(not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol) for symbol in symbols):
        raise ValueError("Invalid explicit symbol list")
    if any(not isinstance(function, str) for function in functions) or not set(functions).issubset(FUNCTIONS):
        raise ValueError("Unsupported fundamental function")
    if len(set(symbols)) != len(symbols) or len(set(functions)) != len(functions):
        raise ValueError("Declare nonempty unique symbols and functions")
    now = utc_time(clock())
    jobs = []
    for symbol in symbols:
        for function in functions:
            request = {"function": function, "symbol": symbol}
            record = store.latest("alpha_vantage", request)
            if record is not None:
                age = now - utc_time(record["observed_at"])
                if age < timedelta(0):
                    raise ValueError("Cached observation is later than the current collection clock")
                if age > cache_max_age:
                    record = None
            jobs.append((request, record))
    required = sum(record is None for _, record in jobs)
    if required > max_requests:
        raise ValueError(f"Plan needs {required} requests, exceeding budget {max_requests}; no calls made")
    if required and client is None:
        raise ValueError("Offline replay lacks fresh cached inputs; no calls made")
    receipts, last_call = [], None
    for request, record in jobs:
        cached = record is not None
        if not cached:
            if last_call is not None:
                sleep(max(0.0, min_interval_seconds - (time.monotonic() - last_call)))
            response = client.fetch_json_response(request["function"], {"symbol": request["symbol"]})
            last_call = time.monotonic()
            record = store.capture("alpha_vantage", request, response.body, observed_at=clock())
        manifest = replay_fundamentals(store, record)
        receipts.append({"request": request, "cache_hit": cached, **manifest})
    return receipts
