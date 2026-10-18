"""Quarterly financial-quality calculations on a single source snapshot.

These diagnostics do not establish historical availability. They intentionally
do not produce ``available_at`` or integrate with the market-factor pipeline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def quarterly_accrual_diagnostic(statements: pd.DataFrame) -> pd.DataFrame:
    """Compute -(TTM net income - TTM operating cash flow) / average assets.

    Required fields: asset, fiscal_year, fiscal_quarter, period_end, currency,
    unit, net_income, operating_cash_flow_ytd, total_assets. Net income is a
    quarterly flow; cash flow is fiscal-year-to-date. Assets are period-end
    stocks. All three financial fields must share the declared currency/unit.

    One row per stable asset/fiscal quarter is required. Choose a consistent
    source format/version before calling; duplicate versions are never averaged
    or silently selected. Missing financial amounts remain missing. A usable
    signal needs four consecutive quarterly flows plus positive assets at the
    beginning and end of those four quarters (five consecutive quarter rows).

    This is snapshot arithmetic, not point-in-time signal formation. Publication
    timestamps, original vintages, historical universe and execution remain
    separate requirements. Caller-owned inputs are not mutated.
    """
    required = [
        "asset", "fiscal_year", "fiscal_quarter", "period_end", "currency", "unit",
        "net_income", "operating_cash_flow_ytd", "total_assets",
    ]
    missing = sorted(set(required) - set(statements.columns))
    if missing:
        raise ValueError(f"Missing statement fields: {missing}")
    df = statements[required].copy()
    for col in ("asset", "currency", "unit"):
        valid = df[col].map(lambda value: isinstance(value, str) and bool(value.strip()))
        if not valid.all():
            raise ValueError(f"{col} must contain nonempty strings")
    for col, lower, upper in (("fiscal_year", 1, 9999), ("fiscal_quarter", 1, 4)):
        values = pd.to_numeric(df[col], errors="raise")
        if values.isna().any() or not (
            np.isfinite(values) & values.between(lower, upper) & (values % 1 == 0)
        ).all():
            raise ValueError(f"Invalid {col}")
        df[col] = values.astype("int64")
    df["period_end"] = pd.to_datetime(df["period_end"], utc=True, errors="raise")
    if df.period_end.isna().any():
        raise ValueError("period_end cannot be missing")
    amount_cols = ["net_income", "operating_cash_flow_ytd", "total_assets"]
    for col in amount_cols:
        df[col] = pd.to_numeric(df[col], errors="raise").astype(float)
        if np.isinf(df[col]).any():
            raise ValueError(f"Infinite amount in {col}")
    keys = ["asset", "fiscal_year", "fiscal_quarter"]
    if df.duplicated(keys).any() or df.duplicated(["asset", "period_end"]).any():
        raise ValueError("Ambiguous duplicate quarter/version")
    for col in ("currency", "unit"):
        if (df.groupby("asset")[col].nunique() > 1).any():
            raise ValueError(f"Normalize changing {col} within each asset before calculation")
    df = df.sort_values(keys).reset_index(drop=True)
    df["_ordinal"] = df.fiscal_year * 4 + df.fiscal_quarter
    grouped = df.groupby("asset", sort=False)
    if grouped.period_end.diff().dropna().le(pd.Timedelta(0)).any():
        raise ValueError("period_end must increase with fiscal quarters")

    prior_ytd = grouped.operating_cash_flow_ytd.shift(1)
    same_year = df.fiscal_year.eq(grouped.fiscal_year.shift(1))
    adjacent = df._ordinal.eq(grouped._ordinal.shift(1) + 1)
    df["operating_cash_flow_quarter"] = (
        df.operating_cash_flow_ytd - prior_ytd
    ).where(same_year & adjacent)
    # A new fiscal year's Q1 is its own YTD, including negative cash flow.
    q1 = df.fiscal_quarter.eq(1)
    df.loc[q1, "operating_cash_flow_quarter"] = df.loc[q1, "operating_cash_flow_ytd"]
    grouped = df.groupby("asset", sort=False)
    four_consecutive = df._ordinal.eq(grouped._ordinal.shift(3) + 3)
    df["ttm_net_income"] = grouped.net_income.transform(
        lambda values: values.rolling(4, min_periods=4).sum()
    ).where(four_consecutive)
    df["ttm_operating_cash_flow"] = grouped.operating_cash_flow_quarter.transform(
        lambda values: values.rolling(4, min_periods=4).sum()
    ).where(four_consecutive)
    opening_assets = grouped.total_assets.shift(4)
    five_consecutive = df._ordinal.eq(grouped._ordinal.shift(4) + 4)
    positive_assets = opening_assets.gt(0) & df.total_assets.gt(0)
    df["average_assets"] = ((opening_assets + df.total_assets) / 2).where(
        five_consecutive & positive_assets
    )
    df["accrual_quality"] = -(
        df.ttm_net_income - df.ttm_operating_cash_flow
    ) / df.average_assets
    df["calculation_ready"] = df.accrual_quality.notna()
    df["timing_status"] = "snapshot_only_availability_unverified"
    return df.drop(columns="_ordinal")
