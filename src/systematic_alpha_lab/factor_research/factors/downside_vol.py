from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class DownsideVol(FactorBase):
    """
    Rolling downside volatility (std of negative returns) over a window.
    """

    def __init__(self, window: int = 60, min_periods: int | None = None, name: str | None = None):
        self.window = window
        self.min_periods = min_periods if min_periods is not None else max(20, window // 2)
        self.name = name or f"downside_vol_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        neg_rets = rets.where(rets < 0, 0.0)
        dvol = neg_rets.rolling(window=self.window, min_periods=self.min_periods).std()
        return dvol

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
