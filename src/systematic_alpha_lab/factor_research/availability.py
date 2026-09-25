"""Conservative as-of selection for one financial-statement feature.

This is a small reference implementation, not a scalable point-in-time database.
The caller must supply actual release timestamps and historical decision rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def fundamentals_asof(filings: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Select the latest available version of the latest fiscal period per asset.

    Inputs: filings(asset, period_end, available_at, value),
    decisions(asset, decision_at). Timestamps are interpreted in UTC; callers
    must convert source-local time correctly and include any execution delay.
    No matches remain missing. Restatements do not overwrite earlier decisions.
    """
    required = {"asset", "period_end", "available_at", "value"}
    if not required.issubset(filings.columns):
        raise ValueError(f"Missing filing fields: {sorted(required-set(filings.columns))}")
    if not {"asset", "decision_at"}.issubset(decisions.columns):
        raise ValueError("Decisions require asset and decision_at")
    f = filings[list(sorted(required))].copy()
    d = decisions[["asset", "decision_at"]].copy()
    if f.isna().any().any() or d.isna().any().any():
        raise ValueError("Required fields cannot be null")
    for frame, column in [(f, "period_end"), (f, "available_at"), (d, "decision_at")]:
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="raise")
        if frame[column].isna().any():
            raise ValueError(f"{column} cannot contain empty timestamps")
    f["value"] = pd.to_numeric(f["value"], errors="raise")
    if not np.isfinite(f["value"]).all():
        raise ValueError("Feature values must be finite")
    if (f["period_end"] > f["available_at"]).any():
        raise ValueError("Financial statements cannot precede their period end")
    if f.duplicated(["asset", "period_end", "available_at"]).any():
        raise ValueError("Ambiguous duplicate filing versions")
    records = []
    groups = {asset: group for asset, group in f.groupby("asset", sort=False)}
    for row in d.itertuples(index=False):
        group = groups.get(row.asset, f.iloc[:0])
        eligible = group[group.available_at <= row.decision_at]
        if eligible.empty:
            records.append((np.nan, pd.NaT, pd.NaT))
        else:
            latest = eligible.sort_values(["period_end", "available_at"]).iloc[-1]
            records.append((latest.value, latest.period_end, latest.available_at))
    result = d.reset_index(drop=True)
    result[["value", "period_end", "available_at"]] = pd.DataFrame(
        records, columns=["value", "period_end", "available_at"], index=result.index
    )
    return result
