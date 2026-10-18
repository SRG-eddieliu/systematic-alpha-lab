"""Descriptive significant-digit diagnostics with explicit timing boundaries.

Definitions and migration notes: docs/benford-diagnostics.md.
Neither a digit discrepancy nor a cell-count screen is a fraud probability.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math

import numpy as np
import pandas as pd

from ..base import FactorBase


def _benford_expected_first() -> np.ndarray:
    return np.array([math.log10(1 + 1 / d) for d in range(1, 10)])


def _benford_expected_second() -> np.ndarray:
    return np.array([
        math.fsum(math.log10(1 + 1 / (10 * first + second)) for first in range(1, 10))
        for second in range(10)
    ])


def _digit_records(values: pd.Series) -> tuple:
    positions, first, second = [], [], []
    zeros = invalid = negative = 0
    for position, value in enumerate(values):
        try:
            # No float conversion, log scaling or context-dependent rounding.
            number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            invalid += 1
            continue
        if not number.is_finite():
            invalid += 1
            continue
        if number.is_zero():
            zeros += 1
            continue
        digits = number.as_tuple().digits
        positions.append(position)
        first.append(digits[0])
        # Mathematical digits include implicit zeros: 9 and 9e3 have D2 = 0.
        second.append(digits[1] if len(digits) > 1 else 0)
        negative += int(number.is_signed())
    return positions, first, second, zeros, invalid, negative


def _first_second_digits(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    positions, first, second, *_ = _digit_records(values)
    index = values.index.take(positions)
    return pd.Series(first, index=index, dtype="int64"), pd.Series(second, index=index, dtype="int64")


def _chi_square(obs_counts: np.ndarray, expected_probs: np.ndarray) -> float:
    """Pearson discrepancy on counts, with no inferential p-value."""
    counts = np.asarray(obs_counts, dtype=float)
    probs = np.asarray(expected_probs, dtype=float)
    if counts.ndim != 1 or counts.shape != probs.shape or not len(counts):
        raise ValueError("Counts and probabilities must be matching nonempty vectors")
    if not np.isfinite(counts).all() or (counts < 0).any() or (counts % 1 != 0).any():
        raise ValueError("Observed counts must be finite nonnegative integers")
    if not np.isfinite(probs).all() or (probs <= 0).any() or not np.isclose(
        probs.sum(), 1.0, rtol=1e-12, atol=1e-12
    ):
        raise ValueError("Expected probabilities must be positive and sum to one")
    if counts.sum() == 0:
        return np.nan
    expected = probs * counts.sum()
    return float(np.sum((counts - expected) ** 2 / expected))


_METRICS = [
    "n_values", "n_nonzero", "n_zero", "n_invalid", "n_negative",
    "chi2_d1", "chi2_d2", "min_expected_d1", "min_expected_d2",
    "cell_count_screen_d1", "cell_count_screen_d2",
]


def _summarize(values: pd.Series) -> dict:
    _, first, second, zeros, invalid, negative = _digit_records(values)
    n = len(first)
    result = {
        "n_values": len(values), "n_nonzero": n, "n_zero": zeros,
        "n_invalid": invalid, "n_negative": negative,
    }
    for digit, samples, expected in (
        (1, first, _benford_expected_first()), (2, second, _benford_expected_second())
    ):
        counts = np.bincount(samples, minlength=10)[1:] if digit == 1 else np.bincount(samples, minlength=10)
        result[f"chi2_d{digit}"] = _chi_square(counts, expected)
        result[f"min_expected_d{digit}"] = float(n * expected.min())
        result[f"cell_count_screen_d{digit}"] = bool(n and counts.min() >= 5 and n * expected.min() >= 5)
    return result


def _validate_labels(frame: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        if not frame[column].map(lambda value: isinstance(value, str) and bool(value.strip())).all():
            raise ValueError(f"{column} requires nonempty string identifiers")


def _aware_times(values: pd.Series, name: str) -> pd.Series:
    timestamps = []
    for value in values:
        try:
            stamp = pd.Timestamp(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid {name} timestamp") from exc
        if pd.isna(stamp) or stamp.tzinfo is None:
            raise ValueError(f"{name} requires nonempty timezone-aware timestamps")
        timestamps.append(stamp.tz_convert("UTC"))
    return pd.Series(timestamps, index=values.index, dtype="datetime64[ns, UTC]")


def _statement_rows(frame: pd.DataFrame, versioned: bool = False) -> pd.DataFrame:
    columns = ["asset", "period_end", "field", "value"]
    if versioned:
        columns += ["available_at", "currency", "unit"]
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing Benford fields: {missing}")
    result = frame[columns].copy()
    _validate_labels(result, ["asset", "field"] + (["currency", "unit"] if versioned else []))
    result["period_end"] = pd.to_datetime(result.period_end, utc=True, errors="raise")
    if result.period_end.isna().any():
        raise ValueError("period_end cannot be missing")
    key = ["asset", "period_end", "field"]
    if versioned:
        result["available_at"] = _aware_times(result.available_at, "available_at")
        if (result.available_at < result.period_end).any():
            raise ValueError("available_at cannot precede period_end")
        key += ["available_at"]
    if result.duplicated(key).any():
        raise ValueError("Ambiguous duplicate field/version")
    return result


def benford_snapshot_diagnostics(statements: pd.DataFrame) -> pd.DataFrame:
    """Summarize explicit financial fields per stable asset and fiscal period.

    Input: asset, period_end, field, value; exactly one row per field/period.
    Caller selects eligible financial amounts with consistent monetary basis.
    Identifiers, fiscal labels and duplicated statement totals are not inferred
    or automatically selected. Negative values use their absolute magnitude;
    zero, missing, nonfinite and unparseable values are counted and excluded.
    """
    frame = _statement_rows(statements)
    rows = []
    for (asset, period_end), group in frame.groupby(["asset", "period_end"], sort=True):
        rows.append({"asset": asset, "period_end": period_end, **_summarize(group.value),
                     "timing_status": "snapshot_only_availability_unverified"})
    result = pd.DataFrame(rows, columns=["asset", "period_end", *_METRICS, "timing_status"])
    result["period_end"] = pd.to_datetime(result.period_end, utc=True)
    return result


def benford_asof_diagnostics(
    filings: pd.DataFrame, decisions: pd.DataFrame, *, fields: list[str]
) -> pd.DataFrame:
    """Reference selection using caller-verified filing/version metadata.

    Filings require snapshot fields plus available_at, currency, unit. Decisions
    require asset, decision_at. Release/decision timestamps must be timezone-aware.
    Select the latest complete period and latest available version of each
    declared field. A published missing value never falls back to a superseded
    value. An older-period restatement cannot replace a newer complete period.

    This row-wise reference does not verify source authenticity, reconstruct
    missing vintages, establish execution delay or implement a trading strategy.
    """
    if not isinstance(fields, (list, tuple)) or not fields or any(
        not isinstance(field, str) or not field.strip() for field in fields
    ) or len(set(fields)) != len(fields):
        raise ValueError("Declare a nonempty unique list of financial fields")
    frame = _statement_rows(filings, versioned=True)
    if not set(frame.field).issubset(fields):
        raise ValueError("Filings contain fields outside the declared field set")
    if not {"asset", "decision_at"}.issubset(decisions.columns):
        raise ValueError("Decisions require asset and decision_at")
    decision_rows = decisions[["asset", "decision_at"]].copy()
    _validate_labels(decision_rows, ["asset"])
    decision_rows["decision_at"] = _aware_times(decision_rows.decision_at, "decision_at")
    groups = {asset: group for asset, group in frame.groupby("asset", sort=False)}
    rows = []
    for decision in decision_rows.itertuples(index=False):
        group = groups.get(decision.asset, frame.iloc[:0])
        eligible = group.loc[group.available_at <= decision.decision_at]
        latest = eligible.sort_values("available_at").drop_duplicates(["period_end", "field"], keep="last")
        complete = latest.groupby("period_end").field.nunique()
        complete = complete[complete.eq(len(fields))]
        selected = latest.loc[latest.period_end.eq(complete.index.max())] if len(complete) else latest.iloc[:0]
        record = {"asset": decision.asset, "decision_at": decision.decision_at,
                  "period_end": pd.NaT, "available_at": pd.NaT,
                  **{key: np.nan for key in _METRICS}, "timing_status": "no_complete_available_period"}
        if not selected.empty:
            if selected.currency.nunique() != 1 or selected.unit.nunique() != 1:
                raise ValueError("Normalize selected field currency/unit before combining amounts")
            record.update(period_end=selected.period_end.iloc[0], available_at=selected.available_at.max(),
                          **_summarize(selected.value), timing_status="supplied_timestamp_asof")
        rows.append(record)
    result = pd.DataFrame(rows, columns=[
        "asset", "decision_at", "period_end", "available_at", *_METRICS, "timing_status"
    ])
    for column in ("decision_at", "period_end", "available_at"):
        result[column] = pd.to_datetime(result[column], utc=True)
    return result


def _compute_benford_scores(df_long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Legacy period-panel helper; the returned index is NOT availability."""
    canonical = df_long.rename(columns={"ticker": "asset", "fiscalDateEnding": "period_end"})
    summary = benford_snapshot_diagnostics(canonical)
    return tuple(summary.pivot(index="period_end", columns="asset", values=column).sort_index()
                 for column in ("chi2_d1", "chi2_d2"))


def _prepare_long(data_loader) -> pd.DataFrame:
    """Read explicit legacy financial fields for snapshot review only."""
    frames = []
    for dataset, fields in (
        ("fundamentals_income_statement", [
            "totalRevenue", "grossProfit", "operatingIncome", "netIncome", "sellingGeneralAndAdministrative"
        ]),
        ("fundamentals_balance_sheet", [
            "totalAssets", "totalCurrentAssets", "totalCurrentLiabilities", "inventory", "propertyPlantEquipment"
        ]),
    ):
        source = data_loader.load_long(dataset=dataset).copy()
        if not {"ticker", "fiscalDateEnding", "period_type"}.issubset(source.columns):
            raise ValueError(f"{dataset} requires ticker, fiscalDateEnding and explicit period_type")
        source = source.loc[source.period_type.eq("quarterly")].copy()
        source["fiscalDateEnding"] = pd.to_datetime(source.fiscalDateEnding, utc=True, errors="raise")
        if source.duplicated(["ticker", "fiscalDateEnding"]).any():
            raise ValueError(f"Ambiguous duplicate quarter in {dataset}; use versioned as-of inputs")
        for field in fields:
            if field in source:
                part = source[["ticker", "fiscalDateEnding", field]].rename(columns={field: "value"})
                frames.append(part.assign(field=field))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ticker", "fiscalDateEnding", "field", "value"]
    )


_TIMING_ERROR = (
    "Automatic Benford daily factors from fiscal-period dates are disabled. "
    "Use compute_snapshot() for descriptive period scores, or benford_asof_diagnostics() "
    "with verified available_at, original field versions, stable asset IDs and explicit decision timestamps. "
    "See docs/benford-diagnostics.md; a one-row shift is not a publication-time policy."
)


class BenfordChiSquareD1(FactorBase):
    """Legacy identifier retained; automatic daily projection is disabled."""

    def __init__(self, name: str | None = None):
        self.name = name or "benford_chi2_d1"

    def compute_snapshot(self, data_loader) -> pd.DataFrame:
        first, _ = _compute_benford_scores(_prepare_long(data_loader))
        return first

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        raise ValueError(_TIMING_ERROR)

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        raise ValueError(_TIMING_ERROR)


class BenfordChiSquareD2(BenfordChiSquareD1):
    """Second-digit period diagnostics; automatic daily projection is disabled."""

    def __init__(self, name: str | None = None):
        self.name = name or "benford_chi2_d2"

    def compute_snapshot(self, data_loader) -> pd.DataFrame:
        _, second = _compute_benford_scores(_prepare_long(data_loader))
        return second
