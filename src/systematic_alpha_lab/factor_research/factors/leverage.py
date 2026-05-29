from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class Leverage(FactorBase):
    """
    Leverage proxy: totalLiabilities / totalAssets (prefers annual).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "leverage"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" in bal.columns:
            bal = bal[bal["period_type"] == "annual"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        bal["totalLiabilities"] = pd.to_numeric(bal.get("totalLiabilities", pd.Series(dtype=float)), errors="coerce")
        bal["totalAssets"] = pd.to_numeric(bal.get("totalAssets", pd.Series(dtype=float)), errors="coerce")
        bal = (
            bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)[["totalLiabilities", "totalAssets"]].mean()
        )
        bal["lev"] = bal["totalLiabilities"] / bal["totalAssets"]
        df = bal.pivot(index="fiscalDateEnding", columns="ticker", values="lev").sort_index()
        ff = factor_setting(getattr(self, "name", "leverage"), self.__class__.__name__, "forward_fill", True)
        if ff:
            price_index = data_loader.load_price_wide(dataset="price_daily").index
            df = df.reindex(price_index).ffill()
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
