from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class OnBalanceVolume(FactorBase):
    """
    On-Balance Volume: cumulative volume signed by daily return direction, shifted one day.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "obv"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_long(dataset="price_daily")
        prices["date"] = pd.to_datetime(prices["date"]).dt.date
        close = prices.pivot(index="date", columns="ticker", values="adjusted_close").sort_index()
        vol = prices.pivot(index="date", columns="ticker", values="volume").sort_index()
        rets = close.pct_change()
        sign = rets.apply(lambda x: x.gt(0).astype(int) - x.lt(0).astype(int))
        obv = (vol * sign).fillna(0).cumsum()
        return obv

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
