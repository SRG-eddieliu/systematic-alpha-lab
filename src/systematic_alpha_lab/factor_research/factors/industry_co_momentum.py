from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase
from .composite_momentum import _exp_weights


def _sector_weighted_scores(
    sector_returns: pd.DataFrame, bucket_sizes: tuple[int, ...], skip_days: int
) -> pd.DataFrame:
    rets = sector_returns.shift(skip_days)
    weights = _exp_weights(len(bucket_sizes))
    stacked = []
    for w, lb in zip(weights, bucket_sizes):
        bucket = (1.0 + rets).rolling(lb).apply(np.prod, raw=True) - 1.0
        stacked.append(w * bucket)
    return sum(stacked)


class IndustryCoMomentum(FactorBase):
    """
    Industry co-momentum: sector-level composite momentum assigned to members.
    """

    def __init__(
        self,
        bucket_sizes: tuple[int, ...] = (21, 63, 126, 252),
        skip_days: int = 21,
        name: str | None = None,
    ):
        self.bucket_sizes = bucket_sizes
        self.skip_days = skip_days
        self.name = name or "industry_co_momentum"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        # Sector map
        sector_map = data_loader.load_sector_map()
        aligned_rets = rets.reindex(columns=sector_map.index)
        sector_rets = aligned_rets.groupby(sector_map, axis=1).mean()
        sector_score = _sector_weighted_scores(sector_rets, self.bucket_sizes, self.skip_days)
        # Broadcast back to tickers
        sector_to_score = {ticker: sector_score[sector] for ticker, sector in sector_map.items() if sector in sector_score.columns}
        df = pd.DataFrame(sector_to_score, index=sector_score.index)
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
