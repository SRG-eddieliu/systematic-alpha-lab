from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class Volatility(FactorBase):
    """
    Trailing realized volatility of daily returns over a configurable window.
    """

    def __init__(self, window: int = 60, min_periods: int | None = None, name: str | None = None):
        self.window = window
        self.min_periods = min_periods if min_periods is not None else max(20, window // 2)
        self.name = name or f"volatility_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        vol = rets.rolling(window=self.window, min_periods=self.min_periods).std()
        return vol

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
