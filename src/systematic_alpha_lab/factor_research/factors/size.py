from __future__ import annotations

import pandas as pd
import numpy as np

from ..base import FactorBase


class Size(FactorBase):
    """
    Log market capitalization using price * quarterly shares outstanding (no annual fallback).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "size_log_mktcap"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        # Quarterly shares only; no fallback to annual
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
        # Align to price calendar and forward-fill between reports
        shares = shares.reindex(prices.index).ffill()
        tickers = prices.columns.intersection(shares.columns)
        cap = prices[tickers] * shares[tickers]
        size = np.log(cap.replace(0, pd.NA))
        return size

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
