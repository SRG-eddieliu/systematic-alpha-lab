from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase
from .composite_momentum import _exp_weights


class VolumeInclusiveICM(FactorBase):
    """
    Volume-inclusive industry co-momentum.
    Uses return * volume as the input score before sector aggregation and exponential weighting.
    """

    def __init__(
        self,
        bucket_sizes: tuple[int, ...] = (21, 63, 126, 252),
        skip_days: int = 21,
        name: str | None = None,
    ):
        self.bucket_sizes = bucket_sizes
        self.skip_days = skip_days
        self.name = name or "volume_inclusive_icm"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices_long = data_loader.load_long(dataset="price_daily")
        prices_long["date"] = pd.to_datetime(prices_long["date"]).dt.date
        price_wide = prices_long.pivot(index="date", columns="ticker", values="adjusted_close").sort_index()
        vol_wide = prices_long.pivot(index="date", columns="ticker", values="volume").sort_index()
        rets = price_wide.pct_change()
        score = rets * vol_wide  # return * volume

        sector_map = data_loader.load_sector_map()
        score = score.reindex(columns=sector_map.index)
        sector_score = score.groupby(sector_map, axis=1).mean().shift(self.skip_days)
        weights = _exp_weights(len(self.bucket_sizes))
        stacked = []
        for w, lb in zip(weights, self.bucket_sizes):
            bucket = sector_score.rolling(lb).mean()
            stacked.append(w * bucket)
        sector_weighted = sum(stacked)
        sector_to_score = {ticker: sector_weighted[sector] for ticker, sector in sector_map.items() if sector in sector_weighted.columns}
        df = pd.DataFrame(sector_to_score, index=sector_weighted.index)
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
