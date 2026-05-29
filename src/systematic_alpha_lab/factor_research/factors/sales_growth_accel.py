from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class SalesGrowthAcceleration(FactorBase):
    """
    Sales growth acceleration: YoY revenue growth minus growth 4 quarters ago (quarterly only).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "sales_growth_accel"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        if "period_type" not in inc.columns:
            raise ValueError("fundamentals_income_statement missing period_type")
        inc = inc[inc["period_type"] == "quarterly"]
        inc["fiscalDateEnding"] = pd.to_datetime(inc["fiscalDateEnding"], errors="coerce").dt.date
        inc = inc[["ticker", "fiscalDateEnding", "totalRevenue"]].copy()
        inc["totalRevenue"] = pd.to_numeric(inc["totalRevenue"], errors="coerce")
        inc = (
            inc.groupby(["ticker", "fiscalDateEnding"], as_index=False)["totalRevenue"]
            .mean()
            .sort_values(["ticker", "fiscalDateEnding"])
        )
        inc["rev_yoy"] = inc.groupby("ticker")["totalRevenue"].pct_change(periods=4, fill_method=None)
        inc["rev_yoy_prev"] = inc.groupby("ticker")["rev_yoy"].shift(4)
        inc["rev_accel"] = inc["rev_yoy"] - inc["rev_yoy_prev"]
        accel = inc.pivot(index="fiscalDateEnding", columns="ticker", values="rev_accel").sort_index()

        prices = data_loader.load_price_wide(dataset="price_daily")
        accel = accel.reindex(prices.index).ffill()
        ff = factor_setting(getattr(self, "name", "sales_growth_accel"), self.__class__.__name__, "forward_fill", True)
        if ff:
            accel = accel.ffill()
        return accel

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
