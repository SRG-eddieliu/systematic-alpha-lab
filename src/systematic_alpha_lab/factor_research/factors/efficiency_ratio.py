from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase


class EfficiencyRatio(FactorBase):
    """
    Path smoothness: total return over window divided by sum of absolute daily returns.
    """

    def __init__(self, window: int = 252, name: str | None = None):
        self.window = window
        self.name = name or f"efficiency_ratio_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        abs_sum = rets.abs().rolling(self.window).sum()
        total_ret = prices / prices.shift(self.window) - 1
        ratio = total_ret / abs_sum.replace(0, np.nan)
        return ratio

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
