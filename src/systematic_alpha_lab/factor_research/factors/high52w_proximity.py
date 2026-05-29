from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class High52wProximity(FactorBase):
    """
    Proximity to 52-week high: price / rolling max(252d) - 1.
    """

    def __init__(self, window: int = 252, name: str | None = None):
        self.window = window
        self.name = name or "high52w_proximity"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        roll_max = prices.rolling(window=self.window, min_periods=self.window // 2).max()
        prox = prices / roll_max - 1.0
        return prox

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
