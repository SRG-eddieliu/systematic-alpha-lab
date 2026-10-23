"""Read-only statement diagnostics; source amounts and eligibility remain unchanged."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from .offline_reader import OfflineDataReader

PROFILE_VERSION = "av_statement_quality_v1"
_METADATA = {
    "fiscalDateEnding", "reportedCurrency", "provider", "source_function", "symbol", "period_type",
    "period_end", "currency", "observed_at", "available_at", "availability_basis", "snapshot_id",
    "normalizer", "asset_id", "identifier_basis", "amount_unit_status", "flow_basis",
}
_MISSING = {"", "none", "null", "nan", "n/a"}


def amount_status(value):
    """Distinguish provider missing tokens, malformed values and nonfinite amounts."""
    if not pd.api.types.is_scalar(value):
        return "nonnumeric"
    if value is None or pd.isna(value) or str(value).strip().lower() in _MISSING:
        return "missing"
    if isinstance(value, bool):
        return "nonnumeric"
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return "nonnumeric"
    return "finite" if number.is_finite() else "nonfinite"


def profile_statement(frame):
    """Inspect a complete v1 table without filling, rescaling or relabeling it."""
    required = {"period_end", "currency", "period_type", "available_at", "asset_id",
                "amount_unit_status", "flow_basis", "observed_at"}
    if not required.issubset(frame.columns) or not frame.columns.is_unique:
        raise ValueError("Statement profile requires the complete normalized table")
    fields = {}
    for name in sorted(set(frame.columns) - _METADATA):
        counts = frame[name].map(amount_status).value_counts()
        fields[name] = {status: int(counts.get(status, 0))
                        for status in ("finite", "missing", "nonnumeric", "nonfinite")}
    return {
        "rows": len(frame), "duplicate_period_rows": int(frame.period_end.duplicated(keep=False).sum()),
        "currencies": sorted(frame.currency.dropna().unique().tolist()),
        "period_types": sorted(frame.period_type.dropna().unique().tolist()),
        "available_at_supplied_rows": int(frame.available_at.notna().sum()),
        "stable_asset_id_supplied_rows": int(frame.asset_id.notna().sum()),
        "amount_unit_statuses": sorted(frame.amount_unit_status.dropna().unique().tolist()),
        "flow_basis_statuses": sorted(frame.flow_basis.dropna().unique().tolist()),
        "amount_fields": fields,
        "earliest_period_end": None if frame.empty else frame.period_end.min().isoformat(),
        "latest_period_end": None if frame.empty else frame.period_end.max().isoformat(),
        "eligibility": "not_certified",
    }


def profile_fundamental_receipts(data_root, receipts):
    """Profile explicitly pinned successful receipts using the existing offline reader.

    Call only on a closed catalog. Missing jobs belong in the batch's full
    coverage ledger, never in this successful-input denominator.
    """
    if not isinstance(receipts, list) or not receipts:
        raise ValueError("Require nonempty explicit successful receipts")
    reader = OfflineDataReader(data_root)
    profiles, seen = [], set()
    for receipt in receipts:
        request = receipt["request"]
        versions = reader.catalog(provider="alpha_vantage", request=request)
        for table, expected in sorted(receipt["tables"].items()):
            identity = (receipt["snapshot_id"], receipt["normalizer"], table)
            if identity in seen:
                raise ValueError("Duplicate quality-profile input pin")
            seen.add(identity)
            found = [item for item in versions if
                     (item["snapshot_id"], item["normalizer"], item["table"]) == identity]
            if len(found) != 1 or found[0]["raw_sha256"] != receipt["raw_sha256"] or (
                found[0]["table_sha256"] != expected["sha256"] or found[0]["rows"] != expected["rows"]
            ):
                raise ValueError("Quality-profile receipt differs from the catalog")
            result = reader.read(snapshot_id=identity[0], normalizer=identity[1], table=identity[2])
            expected_manifest = receipt.get("normalized_manifest_sha256")
            if expected_manifest is None:
                keys = ("snapshot_id", "normalizer", "raw_sha256", "observed_at", "pandas_version", "provenance", "tables")
                expected_manifest = hashlib.sha256(json.dumps(
                    {key: receipt[key] for key in keys}, sort_keys=True, allow_nan=False).encode()).hexdigest()
            if result.metadata["manifest_sha256"] != expected_manifest or (
                result.metadata["observed_at"] != receipt["observed_at"]
            ):
                raise ValueError("Quality-profile complete manifest differs from the receipt")
            profiles.append({"request": request, "table": table, "snapshot_id": identity[0],
                             "raw_sha256": found[0]["raw_sha256"],
                             "table_sha256": found[0]["table_sha256"], **profile_statement(result.frame)})
    return {
        "profile_version": PROFILE_VERSION,
        "profile_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_pins_sha256": hashlib.sha256(json.dumps(
            [{key: row[key] for key in ("request", "table", "snapshot_id", "raw_sha256", "table_sha256")}
             for row in profiles], sort_keys=True).encode()).hexdigest(),
        "tables": profiles, "eligibility": "not_certified",
    }
