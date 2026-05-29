from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase


class HurstExponent(FactorBase):
    """
    Rolling Hurst exponent estimate (rescaled range method) on daily returns, shifted one day.
    """

    def __init__(self, window: int = 252, name: str | None = None):
        self.window = window
        self.name = name or f"hurst_{window}d"

    @staticmethod
    def _hurst(series: pd.Series) -> float:
        s = series.dropna().values
        if len(s) < 20:
            return np.nan
        mean = s.mean()
        dev = s - mean
        cum = np.cumsum(dev)
        R = cum.max() - cum.min()
        S = s.std(ddof=1)
        if S == 0 or np.isnan(S):
            return np.nan
        return np.log(R / S) / np.log(len(s)) if R > 0 else np.nan

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        hurst = rets.rolling(self.window).apply(self._hurst, raw=False)
        return hurst

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
