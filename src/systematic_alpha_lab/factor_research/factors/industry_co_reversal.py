from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase
from .composite_momentum import _exp_weights


class IndustryCoReversal(FactorBase):
    """
    Industry co-reversal: short-horizon sector reversal signal (recent losers expected to mean-revert).
    """

    def __init__(
        self,
        bucket_sizes: tuple[int, ...] = (21, 63),
        skip_days: int = 5,
        name: str | None = None,
    ):
        self.bucket_sizes = bucket_sizes
        self.skip_days = skip_days
        self.name = name or "industry_co_reversal"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        sector_map = data_loader.load_sector_map()
        aligned_rets = rets.reindex(columns=sector_map.index)
        sector_rets = aligned_rets.groupby(sector_map, axis=1).mean().shift(self.skip_days)
        weights = _exp_weights(len(self.bucket_sizes))
        stacked = []
        for w, lb in zip(weights, self.bucket_sizes):
            bucket = (1.0 + sector_rets).rolling(lb).apply(np.prod, raw=True) - 1.0
            stacked.append(w * bucket)
        sector_signal = -1.0 * sum(stacked)  # invert to express reversal (long recent laggards)
        sector_to_score = {ticker: sector_signal[sector] for ticker, sector in sector_map.items() if sector in sector_signal.columns}
        df = pd.DataFrame(sector_to_score, index=sector_signal.index)
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
