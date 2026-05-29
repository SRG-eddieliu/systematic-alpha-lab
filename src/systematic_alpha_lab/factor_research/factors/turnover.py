from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class Turnover(FactorBase):
    """
    Trading turnover: volume / shares outstanding using quarterly shares (no annual fallback).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "turnover"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        price_df = data_loader.load_long(dataset="price_daily")
        price_df["date"] = pd.to_datetime(price_df["date"]).dt.date
        vol_wide = price_df.pivot(index="date", columns="ticker", values="volume").sort_index()

        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing period_type")
        bal = bal[bal["period_type"] == "quarterly"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        col = "commonStockSharesOutstanding"
        if col not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing commonStockSharesOutstanding")
        bal[col] = pd.to_numeric(bal[col], errors="coerce")
        shares = (
            bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)[col]
            .mean()
            .pivot(index="fiscalDateEnding", columns="ticker", values=col)
            .sort_index()
        )
        shares = shares.reindex(vol_wide.index).ffill()
        common = vol_wide.columns.intersection(shares.columns)
        turnover = vol_wide[common].div(shares[common], axis=0)
        return turnover

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
