"""Predeclared monthly chronology and label-availability purging, without fitting."""

from __future__ import annotations

import hashlib
import json
import re
from itertools import pairwise

import pandas as pd

TIMES = ("feature_available_at", "decision_at", "holding_start_at", "holding_end_at", "label_available_at")
SEGMENTS = ("development", "validation", "test")


def _aware_utc(values, name):
    parsed = []
    for value in values:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp) or stamp.tzinfo is None:
            raise ValueError(f"{name} requires nonmissing timezone-aware timestamps")
        parsed.append(stamp.tz_convert("UTC"))
    return pd.Series(pd.to_datetime(parsed, utc=True), index=values.index, dtype="datetime64[ns, UTC]")


def monthly_chronological_split(
    observations: pd.DataFrame, *, source_hashes: dict[str, str]
) -> tuple[pd.DataFrame, dict]:
    """Assign usable decision months 60/20/20, purging labels at later boundaries.

    Require one common decision timestamp per UTC decision month, stable security
    IDs and explicit verified feature, holding and label-availability times.
    Segments count months, not security rows. The two boundaries are floor(3N/5)
    and floor(4N/5), with all three segments required to remain nonempty.

    Development/validation observations whose labels become available at or
    after the next segment's first decision are purged. Touching the boundary
    is excluded conservatively. Test observations are never used for selection.
    A segment emptied by purging raises. Dates and source hashes are supplied
    by the caller: this function checks structure, not source truth or rights.
    It never reads factor/return values, fits a model or modifies its inputs.
    """
    if not isinstance(observations, pd.DataFrame):
        raise TypeError("Study observations must be a DataFrame")
    required = {"asset_id", *TIMES}
    if not observations.columns.is_unique or not required.issubset(observations.columns):
        raise ValueError("Require unique columns with stable asset_id and all explicit study timestamps")
    if (
        not isinstance(source_hashes, dict)
        or not source_hashes
        or any(
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(value, str)
            or not re.fullmatch(r"[0-9a-f]{64}", value)
            for name, value in source_hashes.items()
        )
    ):
        raise ValueError("Require named SHA-256 source hashes before freezing the split")
    if {"decision_month", "assigned_split", "purged", "exclusion_reason"}.intersection(observations.columns):
        raise ValueError("Split output fields already exist; do not silently overwrite a prior plan")
    result = observations.copy(deep=True).reset_index(drop=True)
    if not result.asset_id.map(lambda value: isinstance(value, str) and bool(value.strip())).all():
        raise ValueError("asset_id requires nonempty stable security identifiers")
    for name in TIMES:
        result[name] = _aware_utc(result[name], name)
    if result.duplicated(["asset_id", "decision_at"]).any():
        raise ValueError("Duplicate security/decision observation")
    valid_intervals = (
        result.feature_available_at.le(result.decision_at)
        & result.decision_at.lt(result.holding_start_at)
        & result.holding_start_at.lt(result.holding_end_at)
        & result.holding_end_at.le(result.label_available_at)
    )
    if not valid_intervals.all():
        raise ValueError("Require feature <= decision < holding start < holding end <= label availability")
    result["decision_month"] = result.decision_at.dt.strftime("%Y-%m")
    if result.groupby("decision_month").decision_at.nunique().gt(1).any():
        raise ValueError("Require one shared decision timestamp per monthly cross section")
    months = sorted(result.decision_month.unique())
    n = len(months)
    first, second = 3 * n // 5, 4 * n // 5
    if n < 5 or not (0 < first < second < n):
        raise ValueError("Require at least five usable decision months for three nonempty segments")
    month_groups = (months[:first], months[first:second], months[second:])
    month_to_segment = {month: segment for segment, group in zip(SEGMENTS, month_groups) for month in group}
    result["assigned_split"] = result.decision_month.map(month_to_segment)
    result["purged"] = False
    result["exclusion_reason"] = ""
    boundaries = {}
    for segment, next_segment in pairwise(SEGMENTS):
        boundary = result.loc[result.assigned_split.eq(next_segment), "decision_at"].min()
        boundaries[segment + "_label_cutoff_exclusive"] = boundary.isoformat()
        excluded = result.assigned_split.eq(segment) & result.label_available_at.ge(boundary)
        result.loc[excluded, "purged"] = True
        result.loc[excluded, "exclusion_reason"] = "label_not_available_before_next_segment"
    segment_records = {}
    for segment, group in zip(SEGMENTS, month_groups):
        rows = result.loc[result.assigned_split.eq(segment)]
        retained = rows.loc[~rows.purged]
        if retained.empty:
            raise ValueError(f"Purging leaves no retained observations in {segment}")
        segment_records[segment] = {
            "first_decision_month": group[0],
            "last_decision_month": group[-1],
            "assigned_months": len(group),
            "assigned_rows": len(rows),
            "purged_rows": int(rows.purged.sum()),
            "retained_rows": len(retained),
        }
    timing = result[["asset_id", *TIMES]].sort_values(["decision_at", "asset_id"])
    timing_records = [
        {name: value.isoformat() if isinstance(value, pd.Timestamp) else value for name, value in row.items()}
        for row in timing.to_dict("records")
    ]
    digest = hashlib.sha256(json.dumps(timing_records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = {
        "policy": "monthly_60_20_20_label_availability_purge_v1",
        "source_hashes": dict(sorted(source_hashes.items())),
        "timing_and_identity_sha256": digest,
        "usable_decision_months": months,
        "month_basis": "UTC decision timestamp; missing months are not synthesized",
        "segments": segment_records,
        "boundaries": boundaries,
        "purge_policy": "label_available_at strictly before the next segment's first decision",
        "test_policy": "final evaluation only; not model or signal selection",
        "model_fitted": False,
        "return_values_inspected": False,
        "source_timestamps_or_universe_certified": False,
    }
    return result, manifest
