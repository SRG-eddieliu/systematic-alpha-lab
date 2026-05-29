from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class AssetGrowth(FactorBase):
    """
    Year-over-year asset growth using totalAssets (prefers annual).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "asset_growth"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" in bal.columns:
            bal = bal[bal["period_type"] == "annual"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        bal["totalAssets"] = pd.to_numeric(bal["totalAssets"], errors="coerce")
        bal = bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)["totalAssets"].mean()
        bal = bal.sort_values(["ticker", "fiscalDateEnding"])
        bal["asset_growth"] = bal.groupby("ticker")["totalAssets"].pct_change()
        df = bal.pivot(index="fiscalDateEnding", columns="ticker", values="asset_growth").sort_index()
        ff = factor_setting(getattr(self, "name", "asset_growth"), self.__class__.__name__, "forward_fill", True)
        if ff:
            price_index = data_loader.load_price_wide(dataset="price_daily").index
            df = df.reindex(price_index).ffill()
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
