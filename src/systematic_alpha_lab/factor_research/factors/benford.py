from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pandas as pd

from ..base import FactorBase, factor_setting


def _benford_expected_first() -> np.ndarray:
    return np.array([math.log10(1 + 1 / d) for d in range(1, 10)])


def _benford_expected_second() -> np.ndarray:
    return np.array([math.log10(1 + 1 / (10 + d)) for d in range(0, 10)])


def _first_second_digits(vals: pd.Series) -> Tuple[pd.Series, pd.Series]:
    s = pd.to_numeric(vals, errors="coerce").abs()
    s = s.replace(0, np.nan).dropna()
    # Use string to extract digits after stripping leading zeros
    as_str = s.astype(int).astype(str).str.lstrip("0")
    first = as_str.str[0].dropna().astype(float)
    second = as_str[as_str.str.len() > 1].str[1].astype(float)
    return first, second


def _chi_square(obs_counts: np.ndarray, expected_probs: np.ndarray) -> float:
    if obs_counts.sum() == 0:
        return np.nan
    expected = expected_probs * obs_counts.sum()
    # Avoid division by zero
    mask = expected > 0
    if not mask.any():
        return np.nan
    chi = ((obs_counts[mask] - expected[mask]) ** 2 / expected[mask]).sum()
    return chi


def _compute_benford_scores(df_long: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    first_exp = _benford_expected_first()
    second_exp = _benford_expected_second()

    rows_d1 = []
    rows_d2 = []
    for (ticker, dt), grp in df_long.groupby(["ticker", "fiscalDateEnding"]):
        first, second = _first_second_digits(grp["value"])
        if len(first):
            counts1 = first.value_counts().reindex(range(1, 10), fill_value=0).values
            chi1 = _chi_square(counts1, first_exp)
        else:
            chi1 = np.nan
        if len(second):
            counts2 = second.value_counts().reindex(range(0, 10), fill_value=0).values
            chi2 = _chi_square(counts2, second_exp)
        else:
            chi2 = np.nan
        rows_d1.append({"ticker": ticker, "fiscalDateEnding": dt, "chi2_d1": chi1})
        rows_d2.append({"ticker": ticker, "fiscalDateEnding": dt, "chi2_d2": chi2})

    d1 = pd.DataFrame(rows_d1).pivot(index="fiscalDateEnding", columns="ticker", values="chi2_d1").sort_index()
    d2 = pd.DataFrame(rows_d2).pivot(index="fiscalDateEnding", columns="ticker", values="chi2_d2").sort_index()
    return d1, d2


def _prepare_long(data_loader) -> pd.DataFrame:
    inc = data_loader.load_long(dataset="fundamentals_income_statement")
    bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
    # Quarterly only
    if "period_type" in inc.columns:
        inc = inc[inc["period_type"] == "quarterly"]
    if "period_type" in bal.columns:
        bal = bal[bal["period_type"] == "quarterly"]

    for df in (inc, bal):
        df["fiscalDateEnding"] = pd.to_datetime(df["fiscalDateEnding"], errors="coerce").dt.date

    inc_cols = [
        "totalRevenue",
        "grossProfit",
        "operatingIncome",
        "netIncome",
        "sellingGeneralAndAdministrative",
    ]
    bal_cols = [
        "totalAssets",
        "totalCurrentAssets",
        "totalCurrentLiabilities",
        "inventory",
        "propertyPlantEquipment",
    ]
    frames: List[pd.DataFrame] = []
    for col in inc_cols:
        if col in inc.columns:
            tmp = inc[["ticker", "fiscalDateEnding", col]].rename(columns={col: "value"})
            frames.append(tmp)
    for col in bal_cols:
        if col in bal.columns:
            tmp = bal[["ticker", "fiscalDateEnding", col]].rename(columns={col: "value"})
            frames.append(tmp)
    if not frames:
        return pd.DataFrame(columns=["ticker", "fiscalDateEnding", "value"])
    df_long = pd.concat(frames, ignore_index=True)
    df_long["value"] = pd.to_numeric(df_long["value"], errors="coerce")
    df_long = df_long.dropna(subset=["value", "fiscalDateEnding", "ticker"])
    return df_long


class BenfordChiSquareD1(FactorBase):
    """
    Benford first-digit chi-square on quarterly fundamentals; lower is more conforming.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "benford_chi2_d1"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        df_long = _prepare_long(data_loader)
        d1, _ = _compute_benford_scores(df_long)
        prices = data_loader.load_price_wide(dataset="price_daily")
        d1 = d1.reindex(prices.index).ffill()
        ff = factor_setting(getattr(self, "name", "benford_chi2_d1"), self.__class__.__name__, "forward_fill", True)
        if ff:
            d1 = d1.ffill()
        return d1

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)


class BenfordChiSquareD2(FactorBase):
    """
    Benford second-digit chi-square on quarterly fundamentals; lower is more conforming.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "benford_chi2_d2"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        df_long = _prepare_long(data_loader)
        _, d2 = _compute_benford_scores(df_long)
        prices = data_loader.load_price_wide(dataset="price_daily")
        d2 = d2.reindex(prices.index).ffill()
        ff = factor_setting(getattr(self, "name", "benford_chi2_d2"), self.__class__.__name__, "forward_fill", True)
        if ff:
            d2 = d2.ffill()
        return d2

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
