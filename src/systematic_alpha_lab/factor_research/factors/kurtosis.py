from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class ReturnKurtosis(FactorBase):
    """
    Rolling kurtosis of daily returns over a window.
    """

    def __init__(self, window: int = 60, min_periods: int | None = None, name: str | None = None):
        self.window = window
        self.min_periods = min_periods if min_periods is not None else max(20, window // 2)
        self.name = name or f"kurtosis_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        kurt_df = rets.rolling(window=self.window, min_periods=self.min_periods).apply(lambda col: col.kurt(), raw=False)
        return kurt_df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
