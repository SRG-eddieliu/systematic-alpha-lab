from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class SalesGrowth(FactorBase):
    """
    Year-over-year sales growth using totalRevenue (prefers annual).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "sales_growth"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        if "period_type" in inc.columns:
            inc = inc[inc["period_type"] == "annual"]
        inc["fiscalDateEnding"] = pd.to_datetime(inc["fiscalDateEnding"], errors="coerce").dt.date
        inc["totalRevenue"] = pd.to_numeric(inc["totalRevenue"], errors="coerce")
        inc = inc.sort_values(["ticker", "fiscalDateEnding"])
        inc = inc.groupby(["ticker", "fiscalDateEnding"], as_index=False)["totalRevenue"].mean()
        inc = inc.sort_values(["ticker", "fiscalDateEnding"])
        inc["sales_growth"] = inc.groupby("ticker")["totalRevenue"].pct_change()
        df = inc.pivot(index="fiscalDateEnding", columns="ticker", values="sales_growth").sort_index()
        ff = factor_setting(getattr(self, "name", "sales_growth"), self.__class__.__name__, "forward_fill", True)
        if ff:
            price_index = data_loader.load_price_wide(dataset="price_daily").index
            df = df.reindex(price_index).ffill()
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
