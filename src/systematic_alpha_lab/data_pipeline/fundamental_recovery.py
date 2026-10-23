"""Offline currency quarantine under a new, explicitly partial table contract.

Materialize only in a closed recovery copy. The original v1 normalizer, raw
observations and failed batch ledger remain unchanged. Annual/quarterly tables
contain accepted rows; quarantine/audit rows never count as statement coverage.
This module does not collect, infer a currency or certify research eligibility.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import fundamental_snapshots
from .fundamental_snapshots import FUNCTIONS, normalize_reports
from .snapshot_store import SnapshotStore, utc_time

NORMALIZER = "av_fundamentals_currency_quarantine_v1"
POLICY = {
    "currency_rule": "source_string_fullmatch_AZ_three_characters",
    "invalid_currency": "quarantine_without_imputation",
    "other_validation": "strict_complete_source_before_currency_selection",
    "source_field_preservation": "type_aware_exact_numpy_scalar_item_source_null_allows_scalar_missing",
    "row_identity_columns": ["source_report_key", "source_row_index"],
    "statement_tables": ["annual", "quarterly"],
    "diagnostic_tables": ["quarantine", "normalization_audit"],
    "eligibility": "not_certified",
}
_REPORTS = (("annualReports", "annual"), ("quarterlyReports", "quarterly"))
_RESERVED = {
    "provider", "source_function", "symbol", "period_type", "period_end", "currency",
    "observed_at", "available_at", "availability_basis", "snapshot_id", "normalizer",
    "asset_id", "identifier_basis", "amount_unit_status", "flow_basis",
    "source_report_key", "source_row_index", "source_row_json", "reported_currency_json",
    "quarantine_reason", "source_rows", "accepted_rows", "quarantined_rows",
    "recovery_status", "usable_recovery", "eligibility",
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _strict_json(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate source JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite source JSON constant")

    return json.loads(body, object_pairs_hook=unique, parse_constant=invalid_constant)


def _source_contract(record, function, symbol):
    request = _strict_json(record["request_json"])
    if record["provider"] != "alpha_vantage" or function not in FUNCTIONS or not isinstance(symbol, str) or not (
        re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol)
    ) or request != {"function": function, "symbol": symbol}:
        raise ValueError("Unexpected recovery provider/function/symbol/request")
    if SnapshotStore.request_id("alpha_vantage", request) != record["request_id"] or not (
        re.fullmatch(r"[0-9a-f]{32}", record["id"]) and re.fullmatch(r"[0-9a-f]{64}", record["raw_sha256"])
    ):
        raise ValueError("Recovery source identity/hash differs from its declared request")
    utc_time(record["observed_at"])
    return request


def _currency_reason(row):
    if "reportedCurrency" not in row:
        return "currency_field_missing"
    value = row["reportedCurrency"]
    if value is None or isinstance(value, str) and value.strip().lower() in {"", "none", "null", "nan", "n/a"}:
        return "currency_missing"
    if not isinstance(value, str):
        return "currency_invalid_type"
    return None if re.fullmatch(r"[A-Z]{3}", value) else "currency_invalid_format"


def _status(accepted, quarantined):
    if accepted:
        return "partial" if quarantined else "accepted"
    return "quarantine_only" if quarantined else "no_reports"


def _preserves_source_value(source, actual):
    """Do not let pandas equality hide numeric coercion or integer precision loss."""
    if isinstance(actual, np.generic):
        actual = actual.item()
    if source is None:
        return pd.api.types.is_scalar(actual) and bool(pd.isna(actual))
    if type(source) is not type(actual):
        return False
    if isinstance(source, dict):
        return source.keys() == actual.keys() and all(_preserves_source_value(value, actual[name])
                                                     for name, value in source.items())
    if isinstance(source, list):
        return len(source) == len(actual) and all(_preserves_source_value(left, right)
                                                  for left, right in zip(source, actual))
    if isinstance(source, float):
        return source.hex() == actual.hex()
    return isinstance(source, (str, int, bool)) and source == actual


def _validate_accepted_values(frame, reports, positions):
    for output_index, period_end in frame.period_end.items():
        source = reports[positions[period_end]]
        for name, value in source.items():
            if name not in frame or not _preserves_source_value(value, frame.at[output_index, name]):
                raise ValueError("Accepted source field type/value was not preserved; recovery publication rejected")


def _identity(frame, record, function, symbol):
    frame = frame.copy()
    for name, value in {
        "provider": "alpha_vantage", "source_function": function, "symbol": symbol,
        "snapshot_id": record["id"], "normalizer": NORMALIZER,
    }.items():
        frame[name] = pd.Series(value, index=frame.index, dtype="string")
    frame["observed_at"] = pd.Series(pd.Timestamp(utc_time(record["observed_at"])), index=frame.index,
                                     dtype="datetime64[ns, UTC]")
    return frame


def normalize_quarantined_reports(payload: dict, record: dict, function: str, symbol: str) -> dict[str, pd.DataFrame]:
    """Quarantine invalid currency rows after validating the *entire* source.

    No malformed date, duplicate period, future period or metadata collision can
    disappear through currency filtering. Source array/index and canonical JSON
    retain every quarantined row; the raw object retains its exact source bytes.
    Three uppercase characters mean a reported format, not a verified currency.
    """
    _source_contract(record, function, symbol)
    if not isinstance(payload, dict) or payload.get("symbol") != symbol or any(
        name in payload for name in ("Information", "Note", "Error Message")
    ):
        raise ValueError("Unexpected fundamental source symbol/response")
    observed = pd.Timestamp(utc_time(record["observed_at"]))
    selected, positions, quarantine, audit = {}, {}, [], []
    # Validate both complete arrays before passing any subset to the v1 helper.
    for key, period_type in _REPORTS:
        reports = payload.get(key)
        if not isinstance(reports, list):
            raise ValueError("Expected annualReports and quarterlyReports arrays")  # noqa: TRY004 - v1 schema error contract
        if any(not isinstance(row, dict) or _RESERVED.intersection(row) for row in reports):
            raise ValueError("Unexpected report shape or reserved metadata fields")
        if any("fiscalDateEnding" not in row for row in reports):
            raise ValueError("Fundamental report lacks period")
        dates = pd.to_datetime(pd.Series([row["fiscalDateEnding"] for row in reports], dtype="object"),
                               utc=True, errors="raise")
        if dates.isna().any() or dates.duplicated().any():
            raise ValueError("Missing or duplicate report periods; do not deduplicate source versions")
        if (dates > observed.normalize()).any():
            raise ValueError("Source financial periods exceed the observation date")
        accepted = []
        positions[period_type] = {}
        for index, (row, period_end) in enumerate(zip(reports, dates)):
            # This also rejects non-JSON/nonfinite source values, rather than
            # publishing materializations the strict offline reader cannot read.
            source_json = _json(row)
            reason = _currency_reason(row)
            if reason is None:
                accepted.append(row)
                positions[period_type][period_end] = index
            else:
                quarantine.append({"source_report_key": key, "source_row_index": index,
                                   "source_row_json": source_json, "period_type": period_type,
                                   "period_end": period_end, "quarantine_reason": reason,
                                   "reported_currency_json": _json(row["reportedCurrency"])
                                   if "reportedCurrency" in row else None})
        selected[key] = accepted
        rejected = len(reports) - len(accepted)
        audit.append({"source_report_key": key, "period_type": period_type, "source_rows": len(reports),
                      "accepted_rows": len(accepted), "quarantined_rows": rejected,
                      "recovery_status": _status(len(accepted), rejected), "usable_recovery": bool(accepted)})
    tables = {}
    if any(selected.values()):
        filtered = {**payload, **selected}
        for period_type, frame in normalize_reports(filtered, record, function, symbol).items():
            key = next(key for key, kind in _REPORTS if kind == period_type)
            _validate_accepted_values(frame, payload[key], positions[period_type])
            tables[period_type] = frame.assign(
                normalizer=NORMALIZER, source_report_key=key,
                source_row_index=frame.period_end.map(positions[period_type]).astype("int64"),
            )
    quarantined = pd.DataFrame(quarantine, columns=[
        "source_report_key", "source_row_index", "source_row_json", "period_type", "period_end",
        "quarantine_reason", "reported_currency_json",
    ])
    quarantined["source_row_index"] = quarantined.source_row_index.astype("int64")
    quarantined["period_end"] = pd.to_datetime(quarantined.period_end, utc=True)
    for name in ("source_report_key", "source_row_json", "period_type", "quarantine_reason", "reported_currency_json"):
        quarantined[name] = quarantined[name].astype("string")
    quarantined = _identity(quarantined, record, function, symbol)
    quarantined["currency"] = pd.Series(pd.NA, index=quarantined.index, dtype="string")
    quarantined["available_at"] = pd.Series(pd.NaT, index=quarantined.index, dtype="datetime64[ns, UTC]")
    quarantined["asset_id"] = pd.Series(pd.NA, index=quarantined.index, dtype="string")
    for name, value in {"availability_basis": "not_supplied", "identifier_basis": "provider_symbol_unmapped",
                        "amount_unit_status": "unverified",
                        "flow_basis": "stock" if function == "BALANCE_SHEET" else "unverified"}.items():
        quarantined[name] = pd.Series(value, index=quarantined.index, dtype="string")
    tables["quarantine"] = quarantined
    tables["normalization_audit"] = _identity(pd.DataFrame(audit), record, function, symbol)
    return tables


def _provenance(record, request, tables):
    counts = {row.source_report_key: {name: int(getattr(row, name))
                                     for name in ("source_rows", "accepted_rows", "quarantined_rows")}
              for row in tables["normalization_audit"].itertuples()}
    accepted = sum(row["accepted_rows"] for row in counts.values())
    quarantined = sum(row["quarantined_rows"] for row in counts.values())
    return {
        "normalizer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "base_normalizer": fundamental_snapshots.NORMALIZER,
        "base_normalizer_source_sha256": hashlib.sha256(Path(fundamental_snapshots.__file__).read_bytes()).hexdigest(),
        "policy": json.loads(_json(POLICY)), "policy_sha256": hashlib.sha256(_json(POLICY).encode()).hexdigest(),
        "source_provider": record["provider"], "source_request": request, "source_observed_at": record["observed_at"],
        "source_request_id": record["request_id"],
        "input_snapshots": [{name: record[name] for name in ("id", "raw_sha256", "observed_at")}],
        "source_counts": counts, "source_rows": accepted + quarantined,
        "statement_rows": accepted, "quarantined_rows": quarantined,
        "quarantine_reason_counts": {str(name): int(count) for name, count in
                                     tables["quarantine"].quarantine_reason.value_counts().sort_index().items()},
        "recovery_status": _status(accepted, quarantined), "usable_recovery": bool(accepted),
        "eligibility": "not_certified",
    }


def replay_quarantined_fundamentals(store: SnapshotStore, record: dict) -> dict:
    """Materialize an exact successful raw observation without a network client.

    Existing materializations must retain both source-code hashes, the fixed
    policy and complete source accounting. A drift needs a new normalizer
    version. The supplied record must exactly match its registered source pin.
    """
    registered = store.get(record["id"])
    fields = ("id", "provider", "request_id", "request_json", "observed_at", "raw_sha256", "raw_path")
    if registered is None or any(record.get(name) != registered[name] for name in fields):
        raise ValueError("Recovery source record differs from its catalog pin")
    request = _strict_json(registered["request_json"])
    if not isinstance(request, dict):
        raise ValueError("Recovery request must be an explicit source object")  # noqa: TRY004 - invalid catalog value
    _source_contract(registered, request.get("function"), request.get("symbol"))
    relative = Path(registered["raw_path"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in registered["raw_path"]:
        raise ValueError("Recovery raw source path escapes the data root")
    path = (store.root / relative).resolve(strict=True)
    if not path.is_relative_to(store.root) or not path.is_file():
        raise ValueError("Recovery raw source path escapes the data root")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != registered["raw_sha256"]:
        raise ValueError("Raw snapshot hash mismatch")
    payload = _strict_json(body)
    tables = normalize_quarantined_reports(payload, registered, request["function"], request["symbol"])
    provenance = _provenance(registered, request, tables)
    existing = store.dataset(registered["id"], NORMALIZER)
    if existing is not None:
        if any(existing.get(name) != value for name, value in {
            "snapshot_id": registered["id"], "normalizer": NORMALIZER,
            "raw_sha256": registered["raw_sha256"], "observed_at": registered["observed_at"],
            "provenance": provenance,
        }.items()) or set(existing["tables"]) != set(tables) or any(
            existing["tables"][name]["rows"] != len(frame) for name, frame in tables.items()
        ):
            raise ValueError("Recovery normalizer source/policy/provenance changed; use a new normalizer version")
        return existing
    return store.publish_tables(registered, NORMALIZER, tables, provenance=provenance)
