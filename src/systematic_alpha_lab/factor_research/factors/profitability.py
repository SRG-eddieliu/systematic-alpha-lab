from __future__ import annotations

import pandas as pd
from ..base import FactorBase, factor_setting


class Profitability(FactorBase):
    """
    Profitability: Return on Equity using annual fundamentals only (no company overview).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "profitability_roe"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        for df, name in ((inc, "income_statement"), (bal, "balance_sheet")):
            if "period_type" not in df.columns:
                raise ValueError(f"fundamentals_{name} missing period_type")
        inc = inc[inc["period_type"] == "annual"]
        bal = bal[bal["period_type"] == "annual"]

        inc["fiscalDateEnding"] = pd.to_datetime(inc["fiscalDateEnding"], errors="coerce").dt.date
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        inc = inc[["ticker", "fiscalDateEnding", "netIncome"]].copy()
        bal = bal[["ticker", "fiscalDateEnding", "totalShareholderEquity"]].copy()
        inc["netIncome"] = pd.to_numeric(inc["netIncome"], errors="coerce")
        bal["totalShareholderEquity"] = pd.to_numeric(bal["totalShareholderEquity"], errors="coerce")
        merged = pd.merge(inc, bal, on=["ticker", "fiscalDateEnding"], how="inner")
        merged = merged.groupby(["ticker", "fiscalDateEnding"], as_index=False)[
            ["netIncome", "totalShareholderEquity"]
        ].mean()
        merged["roe"] = merged["netIncome"] / merged["totalShareholderEquity"]
        roe = merged.pivot(index="fiscalDateEnding", columns="ticker", values="roe").sort_index()

        prices = data_loader.load_price_wide(dataset="price_daily")
        roe = roe.reindex(prices.index).ffill()
        ff = factor_setting(getattr(self, "name", "profitability_roe"), self.__class__.__name__, "forward_fill", True)
        if ff:
            roe = roe.ffill()
        return roe

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
