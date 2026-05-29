from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class MaxDailyReturn(FactorBase):
    """
    Max daily return over the past month (21 trading days), shifted one day.
    """

    def __init__(self, window: int = 21, name: str | None = None):
        self.window = window
        self.name = name or f"max_daily_return_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        max_ret = rets.rolling(self.window).max()
        return max_ret

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
