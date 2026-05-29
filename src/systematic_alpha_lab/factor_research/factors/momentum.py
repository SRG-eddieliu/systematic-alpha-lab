from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class Momentum(FactorBase):
    """
    Parameterized momentum: lookback_days window skipping the most recent skip_days.
    """

    def __init__(self, lookback_days: int = 252, skip_days: int = 21, name: str | None = None):
        self.lookback_days = lookback_days
        self.skip_days = skip_days
        self.name = name or f"momentum_{lookback_days}d_{skip_days}dskip"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        past = prices.shift(self.lookback_days + self.skip_days)
        recent = prices.shift(self.skip_days)
        momentum = recent / past - 1.0
        return momentum

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        # Align to next day to avoid look-ahead bias
        return raw_factor.shift(1)
