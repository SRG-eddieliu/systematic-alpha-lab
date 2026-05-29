from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class Accruals(FactorBase):
    """
    Accruals: (Net Income - Operating Cash Flow) / Total Assets (annual), forward-fill configurable.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "accruals"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        cf = data_loader.load_long(dataset="fundamentals_cash_flow")
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        for df in (inc, cf, bal):
            if "period_type" in df.columns:
                df = df[df["period_type"] == "annual"]
        # Refilter after slicing
        inc = inc[inc.get("period_type", "annual").eq("annual")] if "period_type" in inc.columns else inc
        cf = cf[cf.get("period_type", "annual").eq("annual")] if "period_type" in cf.columns else cf
        bal = bal[bal.get("period_type", "annual").eq("annual")] if "period_type" in bal.columns else bal

        for df in (inc, cf, bal):
            if "fiscalDateEnding" in df.columns:
                df["fiscalDateEnding"] = pd.to_datetime(df["fiscalDateEnding"], errors="coerce").dt.date

        inc = inc[["ticker", "fiscalDateEnding", "netIncome"]].copy()
        cf = cf[["ticker", "fiscalDateEnding", "operatingCashflow"]].copy()
        bal = bal[["ticker", "fiscalDateEnding", "totalAssets"]].copy()

        inc["netIncome"] = pd.to_numeric(inc["netIncome"], errors="coerce")
        cf["operatingCashflow"] = pd.to_numeric(cf["operatingCashflow"], errors="coerce")
        bal["totalAssets"] = pd.to_numeric(bal["totalAssets"], errors="coerce")

        merged = inc.merge(cf, on=["ticker", "fiscalDateEnding"], how="inner")
        merged = merged.merge(bal, on=["ticker", "fiscalDateEnding"], how="inner")
        merged = merged.groupby(["ticker", "fiscalDateEnding"], as_index=False)[
            ["netIncome", "operatingCashflow", "totalAssets"]
        ].mean()
        merged["accruals"] = (merged["netIncome"] - merged["operatingCashflow"]) / merged["totalAssets"]
        df = merged.pivot(index="fiscalDateEnding", columns="ticker", values="accruals").sort_index()

        ff = factor_setting(getattr(self, "name", "accruals"), self.__class__.__name__, "forward_fill", True)
        if ff:
            price_index = data_loader.load_price_wide(dataset="price_daily").index
            df = df.reindex(price_index).ffill()
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
