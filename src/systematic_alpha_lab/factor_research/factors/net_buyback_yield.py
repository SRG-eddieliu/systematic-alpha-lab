from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class NetBuybackYield(FactorBase):
    """
    Net buyback yield: negative share growth over 4 quarters (quarterly shares only).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "net_buyback_yield"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing period_type")
        bal = bal[bal["period_type"] == "quarterly"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        col = "commonStockSharesOutstanding"
        if col not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing commonStockSharesOutstanding")
        bal[col] = pd.to_numeric(bal[col], errors="coerce")
        bal = (
            bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)[col]
            .mean()
            .sort_values(["ticker", "fiscalDateEnding"])
        )
        bal["share_growth"] = bal.groupby("ticker")[col].pct_change(periods=4, fill_method=None)
        bal["buyback_yield"] = -bal["share_growth"]  # shrinking share count => positive score
        bby = bal.pivot(index="fiscalDateEnding", columns="ticker", values="buyback_yield").sort_index()

        prices = data_loader.load_price_wide(dataset="price_daily")
        bby = bby.reindex(prices.index).ffill()
        ff = factor_setting(getattr(self, "name", "net_buyback_yield"), self.__class__.__name__, "forward_fill", True)
        if ff:
            bby = bby.ffill()
        return bby

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
