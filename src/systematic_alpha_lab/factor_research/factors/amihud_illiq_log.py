from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase


class AmihudIlliquidityLog(FactorBase):
    """
    Amihud illiquidity with log compression to reduce outlier influence.
    """

    def __init__(self, window: int = 20, name: str | None = None):
        self.window = window
        self.name = name or f"amihud_illiq_log_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_long(dataset="price_daily")
        prices["date"] = pd.to_datetime(prices["date"]).dt.date
        price_wide = prices.pivot(index="date", columns="ticker", values="adjusted_close").sort_index()
        vol_wide = prices.pivot(index="date", columns="ticker", values="volume").sort_index()
        rets = price_wide.pct_change()
        dollar_vol = price_wide * vol_wide
        amihud = (rets.abs() / dollar_vol.replace(0, np.nan)).rolling(self.window).mean()
        amihud = np.log1p(amihud)
        return amihud

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
