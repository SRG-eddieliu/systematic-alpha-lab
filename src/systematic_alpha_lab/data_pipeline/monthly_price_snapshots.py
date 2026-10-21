"""Pinned monthly adjusted-price observations, without market-study certification."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from .snapshot_store import SnapshotStore, utc_time

FUNCTION = "TIME_SERIES_MONTHLY_ADJUSTED"
NORMALIZER = "av_monthly_prices_v1"
SERIES = "Monthly Adjusted Time Series"
FIELDS = {
    "1. open": "open",
    "2. high": "high",
    "3. low": "low",
    "4. close": "close",
    "5. adjusted close": "adjusted_close",
    "6. volume": "volume",
    "7. dividend amount": "dividend_amount",
}


def price_request(symbol, access_mode="user"):
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol):
        raise ValueError("Declare an exact provider symbol")
    if access_mode not in ("user", "public_demo") or (access_mode == "public_demo" and symbol != "IBM"):
        raise ValueError("Public demo is a separate IBM-only source mode")
    return {"function": FUNCTION, "symbol": symbol, "access_mode": access_mode}


def _decode(body):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("Duplicate JSON field in price response")
            result[name] = value
        return result

    return json.loads(body, object_pairs_hook=unique)


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Require an exact source calendar date")
    return pd.Timestamp(value)


def _amount(value, *, positive=False, integer=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Price fields must retain source amount strings")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid price amount") from None
    if not amount.is_finite() or amount < 0 or (positive and amount == 0):
        raise ValueError("Invalid price amount range")
    if integer and (amount != amount.to_integral_value() or amount > 2**63 - 1):
        raise ValueError("Volume must fit a nonnegative integer")
    numeric = float(amount)
    if not math.isfinite(numeric) or (positive and numeric == 0):
        raise ValueError("Price amount exceeds the finite numeric range")
    return amount


def _change(current, previous):
    result = float(Decimal(current) / Decimal(previous) - 1)
    if not math.isfinite(result):
        raise ValueError("Adjusted-price change exceeds the finite numeric range")
    return result


def normalize_monthly_prices(payload, record):
    """Preserve source prices; confirm a closed month only with a later source month.

    A monthly row is a date, not a verified close/publication timestamp. Currency,
    historical security identity, delistings and adjustment vintages stay unknown.
    """
    request = json.loads(record["request_json"])
    if record["provider"] != "alpha_vantage" or set(request) != {"function", "symbol", "access_mode"}:
        raise ValueError("Unexpected price source identity")
    if request != price_request(request["symbol"], request["access_mode"]):
        raise ValueError("Unexpected price function or request fields")
    if not isinstance(payload, dict) or set(payload) != {"Meta Data", SERIES}:
        raise ValueError("Expected a successful monthly adjusted-price response")
    metadata, series = payload["Meta Data"], payload[SERIES]
    if not isinstance(metadata, dict) or metadata.get("2. Symbol") != request["symbol"]:
        raise ValueError("Price symbol differs from the declared request")
    zones = [value for name, value in metadata.items() if name.endswith(". Time Zone")]
    if len(zones) != 1 or not isinstance(zones[0], str):
        raise ValueError("Missing or ambiguous market timezone")
    try:
        zone = ZoneInfo(zones[0])
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("Unsupported market timezone") from None
    observed = pd.Timestamp(utc_time(record["observed_at"]))
    local_date = observed.tz_convert(zone).normalize().tz_localize(None)
    refreshed = _date(metadata.get("3. Last Refreshed"))
    if refreshed > local_date or not isinstance(series, dict) or not series:
        raise ValueError("Empty or future-refreshed price series")
    rows = []
    for date, values in series.items():
        session = _date(date)
        if session > refreshed or not isinstance(values, dict) or set(values) != set(FIELDS):
            raise ValueError("Unexpected monthly price date or fields")
        amounts = {
            target: _amount(
                values[source], positive=target not in ("volume", "dividend_amount"), integer=target == "volume"
            )
            for source, target in FIELDS.items()
        }
        if not (
            amounts["low"]
            <= min(amounts["open"], amounts["close"])
            <= max(amounts["open"], amounts["close"])
            <= amounts["high"]
        ):
            raise ValueError("Inconsistent unadjusted OHLC range")
        row = {"session_date": session, "month": session.strftime("%Y-%m")}
        row.update({target + "_text": values[source] for source, target in FIELDS.items()})
        row.update({name: int(value) if name == "volume" else float(value) for name, value in amounts.items()})
        rows.append(row)
    frame = pd.DataFrame(rows).sort_values("session_date").reset_index(drop=True)
    if frame.month.duplicated().any() or frame.session_date.max() != refreshed:
        raise ValueError("Duplicate monthly rows or refresh/date disagreement")
    frame["closed_month_confirmed_by_later_source_month"] = frame.month.lt(
        refreshed.strftime("%Y-%m")
    ) & frame.month.lt(local_date.strftime("%Y-%m"))
    ordinal = frame.session_date.dt.year * 12 + frame.session_date.dt.month
    confirmed = frame.closed_month_confirmed_by_later_source_month
    pair = ordinal.diff().eq(1) & confirmed & confirmed.shift(1, fill_value=False)
    frame["adjusted_close_change_1m"] = [
        _change(frame.adjusted_close_text.iloc[i], frame.adjusted_close_text.iloc[i - 1]) if valid else np.nan
        for i, valid in enumerate(pair)
    ]
    # The dividend field is already reflected in provider adjusted close; it is
    # retained as evidence and is never added to this ratio a second time.
    frame["forward_adjusted_close_change_1m"] = frame.adjusted_close_change_1m.shift(-1)
    eligible = frame.forward_adjusted_close_change_1m.notna()
    frame["forward_start_date"] = frame.session_date.where(eligible)
    frame["forward_end_date"] = frame.session_date.shift(-1).where(eligible)
    frame = frame.assign(
        provider="alpha_vantage",
        source_function=FUNCTION,
        symbol=request["symbol"],
        access_mode=request["access_mode"],
        sample_status="public_provider_example" if request["access_mode"] == "public_demo" else "user_source_snapshot",
        observed_at=observed,
        snapshot_id=record["id"],
        source_refreshed_date=refreshed,
        market_timezone=zones[0],
        source_staleness_calendar_days=(local_date - refreshed).days,
        adjustment_status="provider_adjusted_snapshot_vintage_unverified",
        identifier_basis="provider_symbol_unmapped",
        return_basis="provider_adjusted_close_ratio_no_separate_dividend_addition",
        historical_universe_status="not_supplied",
        delisting_status="not_supplied",
        currency_status="not_supplied",
        timing_status="source_calendar_dates_only_publication_time_unverified",
    )
    for name in ("asset_id", "currency"):
        frame[name] = pd.Series(pd.NA, index=frame.index, dtype="string")
    frame["available_at"] = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    return frame


def replay_monthly_prices(store: SnapshotStore, record: dict):
    if record != store.get(record["id"]):
        raise ValueError("Pinned price capture metadata differs from catalog")
    store.read_payload(record)  # Verifies immutable raw bytes before any cached replay.
    payload = _decode((store.root / record["raw_path"]).read_bytes())
    provenance = {
        "normalizer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_request": json.loads(record["request_json"]),
        "source_observed_at": record["observed_at"],
        "source_provider": record["provider"],
        "month_policy": "strictly_before_observation_and_source_refresh_month",
        "return_policy": "adjacent_confirmed_months_only_provider_adjusted_close_ratio",
    }
    version = NORMALIZER + "_" + hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:20]
    existing = store.dataset(record["id"], version)
    if existing is not None:
        return existing
    frame = normalize_monthly_prices(payload, record)
    return store.publish_tables(record, version, {"monthly_prices": frame}, provenance=provenance)


def ingest_monthly_prices(
    client,
    store: SnapshotStore,
    *,
    symbols,
    access_mode="user",
    max_requests=3,
    cache_max_age=timedelta(hours=24),
    min_interval_seconds=15,
    clock=utc_time,
    sleep=time.sleep,
):
    """Preflight the whole budget; stop without retries or source-mode fallback."""
    if not isinstance(symbols, (list, tuple)) or not symbols:
        raise ValueError("Declare nonempty unique symbols")
    requests = [price_request(symbol, access_mode) for symbol in symbols]
    if len(set(symbols)) != len(symbols):
        raise ValueError("Declare nonempty unique symbols")
    if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests < 0:
        raise ValueError("Invalid price request budget")
    if not isinstance(cache_max_age, timedelta) or cache_max_age < timedelta(0):
        raise ValueError("Invalid price cache age")
    if (
        isinstance(min_interval_seconds, bool)
        or not isinstance(min_interval_seconds, (int, float))
        or not (math.isfinite(min_interval_seconds) and 0 <= min_interval_seconds <= 60)
    ):
        raise ValueError("Invalid price request interval")
    if client is not None and getattr(client, "api_key", None) == "demo" and access_mode != "public_demo":
        raise ValueError("Demo credentials require the explicit public-demo source mode")
    now, jobs = utc_time(clock()), []
    for request in requests:
        record = store.latest("alpha_vantage", request)
        if record is not None:
            age = now - utc_time(record["observed_at"])
            if age < timedelta(0):
                raise ValueError("Cached price observation is in the future")
            if age > cache_max_age:
                record = None
        jobs.append((request, record))
    required = sum(record is None for _, record in jobs)
    if required > max_requests or (required and client is None):
        raise ValueError("Price budget/cache preflight failed; no calls made")
    results, last_call = [], None
    for request, record in jobs:
        cached = record is not None
        if not cached:
            if last_call is not None:
                sleep(max(0.0, min_interval_seconds - (time.monotonic() - last_call)))
            response = client.fetch_json_response(FUNCTION, {"symbol": request["symbol"]})
            last_call = time.monotonic()
            observed = clock()
            preview = {
                "provider": "alpha_vantage",
                "id": "preflight",
                "request_json": json.dumps(request),
                "observed_at": observed,
            }
            normalize_monthly_prices(_decode(response.body), preview)
            record = store.capture("alpha_vantage", request, response.body, observed_at=observed)
        results.append({"request": request, "cache_hit": cached, "manifest": replay_monthly_prices(store, record)})
    return results
