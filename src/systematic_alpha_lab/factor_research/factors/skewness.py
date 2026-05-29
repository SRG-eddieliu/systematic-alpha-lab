from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class ReturnSkewness(FactorBase):
    """
    Rolling skewness of daily returns over a window.
    """

    def __init__(self, window: int = 60, min_periods: int | None = None, name: str | None = None):
        self.window = window
        self.min_periods = min_periods if min_periods is not None else max(20, window // 2)
        self.name = name or f"skewness_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()

        def rolling_skew(x: pd.Series) -> float:
            x = x.dropna()
            if len(x) < self.min_periods:
                return pd.NA
            return x.skew()

        skew_df = rets.rolling(window=self.window, min_periods=self.min_periods).apply(lambda col: col.skew(), raw=False)
        return skew_df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
