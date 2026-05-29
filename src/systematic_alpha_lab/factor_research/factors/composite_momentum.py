from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase


def _exp_weights(k: int) -> np.ndarray:
    # j=1 is most recent bucket
    idx = np.arange(1, k + 1, dtype=float)
    w = 2.0 ** ((idx - 1) / (k - 1))
    return w / w.sum()


def _weighted_bucket_returns(
    returns: pd.DataFrame, bucket_sizes: tuple[int, ...], skip_days: int
) -> pd.DataFrame:
    """
    Compute exponentially weighted bucket returns.
    - returns: daily return wide DataFrame (Date x Ticker)
    - bucket_sizes: tuple of lookback window sizes in days, ordered from most recent to oldest
    - skip_days: exclude the most recent N days to avoid look-ahead
    """
    rets = returns.shift(skip_days)
    weights = _exp_weights(len(bucket_sizes))
    stacked = []
    for w, lb in zip(weights, bucket_sizes):
        bucket = (1.0 + rets).rolling(lb).apply(np.prod, raw=True) - 1.0
        stacked.append(w * bucket)
    return sum(stacked)


class CompositeMomentum(FactorBase):
    """
    Composite momentum: exponentially weighted mix of multiple lookback buckets.
    Uses stock-level returns only.
    """

    def __init__(
        self,
        bucket_sizes: tuple[int, ...] = (21, 63, 126, 252),
        skip_days: int = 21,
        name: str | None = None,
    ):
        self.bucket_sizes = bucket_sizes
        self.skip_days = skip_days
        self.name = name or "composite_momentum"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        cmc = _weighted_bucket_returns(rets, self.bucket_sizes, self.skip_days)
        return cmc

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        # Lag by one day for safety
        return raw_factor.shift(1)
