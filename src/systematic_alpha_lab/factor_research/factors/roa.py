from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class ReturnOnAssets(FactorBase):
    """
    Return on Assets: netIncome / totalAssets, using fundamentals (prefers annual).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "roa"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        # Prefer annual rows if period_type present
        if "period_type" in inc.columns:
            inc = inc[inc["period_type"] == "annual"]
        if "period_type" in bal.columns:
            bal = bal[bal["period_type"] == "annual"]
        inc["fiscalDateEnding"] = pd.to_datetime(inc["fiscalDateEnding"], errors="coerce").dt.date
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        inc = inc[["ticker", "fiscalDateEnding", "netIncome"]].copy()
        bal = bal[["ticker", "fiscalDateEnding", "totalAssets"]].copy()
        inc["netIncome"] = pd.to_numeric(inc["netIncome"], errors="coerce")
        bal["totalAssets"] = pd.to_numeric(bal["totalAssets"], errors="coerce")
        merged = pd.merge(inc, bal, on=["ticker", "fiscalDateEnding"], how="inner")
        # Deduplicate by averaging when multiple rows per ticker/date exist
        merged = (
            merged.groupby(["ticker", "fiscalDateEnding"], as_index=False)[["netIncome", "totalAssets"]].mean()
        )
        merged["roa"] = merged["netIncome"] / merged["totalAssets"]
        # Use pivot_table to guard against any remaining duplicate keys
        df = merged.pivot_table(index="fiscalDateEnding", columns="ticker", values="roa", aggfunc="mean").sort_index()
        ff = factor_setting(getattr(self, "name", "roa"), self.__class__.__name__, "forward_fill", True)
        if ff:
            price_index = data_loader.load_price_wide(dataset="price_daily").index
            df = df.reindex(price_index).ffill()
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
