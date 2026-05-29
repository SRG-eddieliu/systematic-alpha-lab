from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class DollarVolume(FactorBase):
    """
    Rolling average dollar volume (price * volume), a liquidity proxy.
    """

    def __init__(self, window: int = 20, name: str | None = None):
        self.window = window
        self.name = name or f"dollar_volume_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        df = data_loader.load_long(dataset="price_daily")
        price_col = "adjusted_close" if "adjusted_close" in df.columns else "close"
        price_wide = df.pivot(index="date", columns="ticker", values=price_col).sort_index()
        vol_wide = df.pivot(index="date", columns="ticker", values="volume").sort_index()
        dollar_vol = price_wide * vol_wide
        dv_mean = dollar_vol.rolling(window=self.window, min_periods=max(5, self.window // 2)).mean()
        return dv_mean

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
