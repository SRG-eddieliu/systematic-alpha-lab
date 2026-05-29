from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class RDIntensity(FactorBase):
    """
    R&D intensity: researchAndDevelopment / totalRevenue (annual), forward-fill configurable.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "rd_intensity"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        if "period_type" in inc.columns:
            inc = inc[inc["period_type"] == "annual"]
        inc["fiscalDateEnding"] = pd.to_datetime(inc["fiscalDateEnding"], errors="coerce").dt.date
        inc["researchAndDevelopment"] = pd.to_numeric(inc.get("researchAndDevelopment", pd.Series(dtype=float)), errors="coerce")
        inc["totalRevenue"] = pd.to_numeric(inc.get("totalRevenue", pd.Series(dtype=float)), errors="coerce")
        inc = inc.groupby(["ticker", "fiscalDateEnding"], as_index=False)[["researchAndDevelopment", "totalRevenue"]].mean()
        inc["rd_intensity"] = inc["researchAndDevelopment"] / inc["totalRevenue"]
        df = inc.pivot(index="fiscalDateEnding", columns="ticker", values="rd_intensity").sort_index()

        ff = factor_setting(getattr(self, "name", "rd_intensity"), self.__class__.__name__, "forward_fill", True)
        if ff:
            price_index = data_loader.load_price_wide(dataset="price_daily").index
            df = df.reindex(price_index).ffill()
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
