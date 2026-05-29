from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class MeanReversion(FactorBase):
    """
    Reversal signal: negative of past N-day return.
    """

    def __init__(self, lookback_days: int = 5, name: str | None = None):
        self.lookback_days = lookback_days
        self.name = name or f"mean_reversion_{lookback_days}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rev = prices.pct_change(periods=self.lookback_days)
        # Use negative to capture reversal
        return -rev

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
