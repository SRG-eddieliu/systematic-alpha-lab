"""Exact Yahoo financial-timeseries observations, without yfinance reshaping.

The parser follows the raw endpoint consumed by yfinance 1.7.0's official
``scrapers/fundamentals.py``. No yfinance import, client, field mapping, fiscal
year selection, currency imputation or statement-completeness claim occurs.
Each captured response may represent only one chunk of a statement request.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .snapshot_store import SnapshotStore, utc_time

PROVIDER = "yahoo_financial_timeseries"
NORMALIZER = "yf_timeseries_cells_v1"
ADAPTER_VERSION = "1.7.0"
ADAPTER_SOURCE_SHA256 = "26198c3ef0d577255f63b6f84106150ca2f3bb5bc86eb56e60c4cdcb73948f86"
STATEMENTS = ("income", "balance-sheet", "cash-flow")
POLICY = {
    "capture_layer": "original_financial_timeseries_response_bytes",
    "numeric_representation": "original_json_number_lexeme_and_type",
    "period_end": "source_asOfDate_calendar_label_UTC_not_availability",
    "coverage": "single_response_chunk_not_complete_statement",
    "missing_metadata": "unknown_without_imputation",
    "eligibility": "not_certified",
}


class _Integer(str):
    pass


class _Float(str):
    pass


def _parse(body):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("Duplicate Yahoo JSON field")
            result[name] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite Yahoo JSON constant")

    try:
        return json.loads(body, object_pairs_hook=unique, parse_int=_Integer, parse_float=_Float,
                          parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Invalid Yahoo JSON response") from None


def _json(value):
    """Canonical structure while retaining original numeric tokens exactly."""
    if isinstance(value, (_Integer, _Float)):
        return str(value)
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(name, ensure_ascii=False) + ":" + _json(value[name])
                              for name in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _request(symbol, statement, contract_sha256=None):
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol):
        raise ValueError("Require an explicit Yahoo symbol")
    if not isinstance(statement, str) or statement not in STATEMENTS:
        raise ValueError("Unsupported explicit Yahoo statement")
    if contract_sha256 is not None and (not isinstance(contract_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", contract_sha256
    )):
        raise ValueError("Invalid field-contract fingerprint")
    result = {"symbol": symbol, "statement": statement, "frequency": "annual", "adapter": "yfinance",
              "adapter_version": ADAPTER_VERSION, "adapter_source_sha256": ADAPTER_SOURCE_SHA256}
    if contract_sha256 is not None:
        result["contract_sha256"] = contract_sha256
    return result


def _singleton(value, label):
    values = [value] if type(value) is str else value
    if not isinstance(values, list) or len(values) != 1 or type(values[0]) is not str or not values[0]:
        raise ValueError("Yahoo meta must declare one explicit " + label)
    return values[0]


def _metadata(item, name):
    value = item.get(name)
    if value is not None and type(value) is not str:
        raise ValueError("Unsupported Yahoo source metadata type")
    return value, _json(value) if name in item else None


def _period(item, observed):
    value, encoded = _metadata(item, "asOfDate")
    if value is None:
        return pd.NaT, encoded, "unknown"
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Invalid Yahoo source calendar date")
    try:
        stamp = pd.Timestamp(value, tz="UTC")
        if stamp > observed.normalize():
            raise ValueError("Yahoo source financial period exceeds observation date")
    except (ValueError, OverflowError):
        raise ValueError("Invalid or future Yahoo source calendar date") from None
    return stamp, encoded, "source_calendar_label"


def _value(item):
    reported = item.get("reportedValue")
    if reported is not None and not isinstance(reported, dict):
        raise ValueError("Unsupported Yahoo reportedValue shape")
    if reported is None or "raw" not in reported:
        return None, "absent", "unavailable"
    value = reported["raw"]
    if value is None:
        return "null", "null", "source_null"
    if isinstance(value, (_Integer, _Float)) and Decimal(value).is_finite():
        return str(value), "integer" if isinstance(value, _Integer) else "float", "reported_numeric"
    raise ValueError("Unsupported Yahoo reported numeric value")


def _tables(body, request, record):
    payload = _parse(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("timeseries"), dict):
        raise ValueError("Expected a Yahoo timeseries response object")  # noqa: TRY004 - source schema error
    response = payload["timeseries"]
    if response.get("error") is not None:
        raise ValueError("Yahoo timeseries reports a provider error")
    results = response.get("result")
    if results is not None and not isinstance(results, list):
        raise ValueError("Expected Yahoo timeseries result array")
    observed = pd.Timestamp(utc_time(record["observed_at"]))
    rows, audits, metrics = [], [], set()
    if not results:
        audits.append({"source_result_index": -1, "source_metric": None, "source_meta_json": None,
                       "source_timestamp_json": None, "source_item_count": 0, "numeric_item_count": 0,
                       "source_symbol_verified": False, "status": "empty_result" if results == [] else "result_unknown"})
    for result_index, result in enumerate(results or []):
        if not isinstance(result, dict) or not isinstance(result.get("meta"), dict):
            raise ValueError("Expected Yahoo result metadata object")  # noqa: TRY004 - source schema error
        meta = result["meta"]
        if _singleton(meta.get("symbol"), "symbol") != request["symbol"]:
            raise ValueError("Yahoo response symbol differs from its explicit request")
        metric = _singleton(meta.get("type"), "metric type")
        if not re.fullmatch(r"annual[A-Za-z][A-Za-z0-9]{0,159}", metric) or metric in metrics:
            raise ValueError("Unsupported or duplicate Yahoo annual metric label")
        metrics.add(metric)
        if set(result) - {"meta", "timestamp", metric}:
            raise ValueError("Yahoo meta type differs from actual metric fields")
        timestamps = result.get("timestamp")
        if timestamps is not None and (not isinstance(timestamps, list) or any(
            not isinstance(value, _Integer) for value in timestamps
        ) or len(set(timestamps)) != len(timestamps)):
            raise ValueError("Invalid or duplicate Yahoo source timestamps")
        items = result.get(metric)
        if items is not None and not isinstance(items, list):
            raise ValueError("Expected Yahoo metric item array")
        periods, numeric_count = set(), 0
        for item_index, item in enumerate(items or []):
            if not isinstance(item, dict):
                raise ValueError("Expected Yahoo financial item object")  # noqa: TRY004 - source schema error
            period, as_of_json, period_status = _period(item, observed)
            period_label = None if pd.isna(period) else period.isoformat()
            if period_label in periods:
                raise ValueError("Duplicate Yahoo metric/period label; do not deduplicate")
            periods.add(period_label)
            value_json, value_type, value_status = _value(item)
            numeric_count += value_status == "reported_numeric"
            currency, currency_json = _metadata(item, "currencyCode")
            source_period, source_period_json = _metadata(item, "periodType")
            rows.append({
                "source_result_index": result_index, "source_item_index": item_index,
                "source_metric": metric, "source_item_json": _json(item),
                "source_value_json": value_json, "source_value_type": value_type, "value_status": value_status,
                "period_end": period, "period_end_status": period_status, "source_as_of_date_json": as_of_json,
                "currency": currency, "source_currency_json": currency_json,
                "currency_status": "source_format_only" if currency and re.fullmatch(r"[A-Z]{3}", currency)
                else "unknown" if currency is None else "unrecognized_source_format",
                "source_period_type": source_period, "source_period_type_json": source_period_json,
                "source_period_type_status": "unknown" if source_period is None else "unverified_source_label",
            })
        audits.append({"source_result_index": result_index, "source_metric": metric,
                       "source_meta_json": _json(meta),
                       "source_timestamp_json": _json(timestamps) if "timestamp" in result else None,
                       "source_item_count": len(items or []), "numeric_item_count": numeric_count,
                       "source_symbol_verified": True,
                       "status": "observed_cells" if items else "metric_empty" if items == [] else "metric_items_unknown"})
    columns = ["source_result_index", "source_item_index", "source_metric", "source_item_json",
               "source_value_json", "source_value_type", "value_status", "period_end", "period_end_status",
               "source_as_of_date_json", "currency", "source_currency_json", "currency_status",
               "source_period_type", "source_period_type_json", "source_period_type_status"]
    facts = pd.DataFrame(rows, columns=columns)
    for name in ("source_result_index", "source_item_index"):
        facts[name] = facts[name].astype("int64")
    facts["period_end"] = pd.to_datetime(facts.period_end, utc=True)
    for name in set(columns) - {"source_result_index", "source_item_index", "period_end"}:
        facts[name] = facts[name].astype("string")
    for name in ("period_start", "available_at"):
        facts[name] = pd.Series(pd.NaT, index=facts.index, dtype="datetime64[ns, UTC]")
    for name, value in {"amount_unit_status": "unverified", "flow_basis": "unverified",
                        "availability_basis": "not_supplied", "identifier_basis": "provider_symbol_unmapped"}.items():
        facts[name] = pd.Series(value, index=facts.index, dtype="string")
    facts["asset_id"] = pd.Series(pd.NA, index=facts.index, dtype="string")
    tables = {"facts": facts, "audit": pd.DataFrame(audits)}
    for frame in tables.values():
        for name, value in {"provider": PROVIDER, "symbol": request["symbol"], "snapshot_id": record["id"],
                            "normalizer": NORMALIZER, "source_statement": request["statement"],
                            "source_frequency": "annual", "eligibility": "not_certified"}.items():
            frame[name] = pd.Series(value, index=frame.index, dtype="string")
        frame["observed_at"] = pd.Series(observed, index=frame.index, dtype="datetime64[ns, UTC]")
    return tables


def _provenance(record, request, tables):
    return {
        "normalizer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_provider": PROVIDER, "source_request": request, "source_observed_at": record["observed_at"],
        "adapter_version": ADAPTER_VERSION, "adapter_source_sha256": ADAPTER_SOURCE_SHA256,
        "policy": POLICY, "policy_sha256": hashlib.sha256(_json(POLICY).encode()).hexdigest(),
        "input_snapshots": [{name: record[name] for name in ("id", "raw_sha256", "observed_at")}],
        "fact_rows": len(tables["facts"]), "audit_rows": len(tables["audit"]),
        "numeric_fact_rows": int(tables["facts"].value_status.eq("reported_numeric").sum()),
        "source_symbol_verified": bool(tables["audit"].source_symbol_verified.all()),
        "statement_completeness": "not_certified_response_chunk_only", "eligibility": "not_certified",
    }


def replay_yahoo_timeseries(store: SnapshotStore, record: dict) -> dict:
    """Replay one exact registered response, without network or latest selection."""
    registered = store.get(record["id"])
    names = ("id", "provider", "request_id", "request_json", "raw_sha256", "raw_path", "observed_at")
    if registered is None or any(record.get(name) != registered[name] for name in names):
        raise ValueError("Yahoo source record differs from its exact registered pin")
    try:
        request = _parse(registered["request_json"])
        canonical = _request(request["symbol"], request["statement"], request.get("contract_sha256"))
    except (KeyError, TypeError, json.JSONDecodeError):
        raise ValueError("Invalid explicit Yahoo request metadata") from None
    if registered["provider"] != PROVIDER or request != canonical or registered["request_id"] != (
        SnapshotStore.request_id(PROVIDER, request)
    ):
        raise ValueError("Yahoo provider/request identity differs")
    relative = Path(registered["raw_path"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in registered["raw_path"]:
        raise ValueError("Yahoo raw source escapes the data root")
    path = (store.root / relative).resolve(strict=True)
    if not path.is_relative_to(store.root) or not path.is_file():
        raise ValueError("Yahoo raw source escapes the data root")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != registered["raw_sha256"]:
        raise ValueError("Yahoo raw response hash mismatch")
    tables = _tables(body, request, registered)
    provenance = _provenance(registered, request, tables)
    existing = store.dataset(registered["id"], NORMALIZER)
    if existing is not None:
        expected = {"snapshot_id": registered["id"], "normalizer": NORMALIZER,
                    "raw_sha256": registered["raw_sha256"], "observed_at": registered["observed_at"],
                    "provenance": provenance}
        if any(existing.get(name) != value for name, value in expected.items()) or set(existing["tables"]) != set(
            tables
        ) or any(existing["tables"][name]["rows"] != len(frame) for name, frame in tables.items()):
            raise ValueError("Yahoo normalizer source/policy changed; use a new normalizer version")
        return existing
    return store.publish_tables(registered, NORMALIZER, tables, provenance=provenance)


def capture_yahoo_timeseries(store: SnapshotStore, *, symbol, statement, body, observed_at,
                            contract_sha256=None) -> dict:
    """Capture untouched response bytes and materialize source cells in a new version.

    The caller owns HTTP authorization, status checking, transport accounting,
    failure-body retention and the closed-write-root boundary. This function
    neither makes requests nor claims that all requested metrics were returned.
    """
    if not isinstance(body, bytes):
        raise TypeError("Require the original Yahoo JSON response bytes")
    request = _request(symbol, statement, contract_sha256)
    # Reject mismatched/malformed responses before registering a source capture.
    _tables(body, request, {"id": "0" * 32, "observed_at": utc_time(observed_at).isoformat()})
    record = store.capture(PROVIDER, request, body, observed_at=observed_at)
    return {"record": record, "manifest": replay_yahoo_timeseries(store, record)}
