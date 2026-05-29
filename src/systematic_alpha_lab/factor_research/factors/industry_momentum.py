from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class IndustryMomentum(FactorBase):
    """
    Industry momentum: sector-level 6-1 month momentum assigned to constituents.
    """

    def __init__(self, name: str | None = None, lookback_days: int = 126, skip_days: int = 21):
        self.name = name or "industry_momentum"
        self.lookback_days = lookback_days
        self.skip_days = skip_days

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        sector_map = data_loader.load_sector_map()
        prices = data_loader.load_price_wide(dataset="price_daily")
        # Align to tickers with sector info
        sector_map = sector_map.dropna()
        common = prices.columns.intersection(sector_map.index)
        prices = prices[common]
        sector_map = sector_map.loc[common]

        # 6-1 month momentum: price(t-1m) / price(t-6m) - 1
        ret = prices.shift(self.skip_days) / prices.shift(self.lookback_days) - 1

        # Compute sector averages
        ret_sector = ret.copy()
        ret_sector.columns = sector_map.values
        sector_avg = ret_sector.groupby(level=0, axis=1).mean()

        # Broadcast sector momentum back to tickers
        sector_avg = sector_avg[sector_map.unique()]
        sector_mom = sector_avg[sector_map.values]
        sector_mom.columns = sector_map.index
        return sector_mom

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
