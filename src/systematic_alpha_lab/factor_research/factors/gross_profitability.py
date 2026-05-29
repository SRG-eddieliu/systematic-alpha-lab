from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class GrossProfitability(FactorBase):
    """
    Gross profitability: grossProfit / totalAssets using quarterly fundamentals.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "gross_profitability"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        for df, nm in ((inc, "income_statement"), (bal, "balance_sheet")):
            if "period_type" not in df.columns:
                raise ValueError(f"fundamentals_{nm} missing period_type")
        inc = inc[inc["period_type"] == "quarterly"]
        bal = bal[bal["period_type"] == "quarterly"]
        inc["fiscalDateEnding"] = pd.to_datetime(inc["fiscalDateEnding"], errors="coerce").dt.date
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        inc = inc[["ticker", "fiscalDateEnding", "grossProfit"]].copy()
        bal = bal[["ticker", "fiscalDateEnding", "totalAssets"]].copy()
        inc["grossProfit"] = pd.to_numeric(inc["grossProfit"], errors="coerce")
        bal["totalAssets"] = pd.to_numeric(bal["totalAssets"], errors="coerce")
        merged = pd.merge(inc, bal, on=["ticker", "fiscalDateEnding"], how="inner")
        merged = merged.groupby(["ticker", "fiscalDateEnding"], as_index=False)[["grossProfit", "totalAssets"]].mean()
        merged["gp"] = merged["grossProfit"] / merged["totalAssets"]
        gp = merged.pivot(index="fiscalDateEnding", columns="ticker", values="gp").sort_index()

        prices = data_loader.load_price_wide(dataset="price_daily")
        gp = gp.reindex(prices.index).ffill()
        ff = factor_setting(getattr(self, "name", "gross_profitability"), self.__class__.__name__, "forward_fill", True)
        if ff:
            gp = gp.ffill()
        return gp

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
