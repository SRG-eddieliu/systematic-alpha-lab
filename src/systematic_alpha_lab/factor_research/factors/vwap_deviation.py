from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class VWAPDeviation(FactorBase):
    """
    Deviation of price from rolling VWAP over a given window (mean reversion signal), shifted one day.
    """

    def __init__(self, window: int = 21, name: str | None = None):
        self.window = window
        self.name = name or f"vwap_dev_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_long(dataset="price_daily")
        prices["date"] = pd.to_datetime(prices["date"]).dt.date
        close = prices.pivot(index="date", columns="ticker", values="adjusted_close").sort_index()
        vol = prices.pivot(index="date", columns="ticker", values="volume").sort_index()
        dollar = close * vol
        vwap = dollar.rolling(self.window).sum() / vol.rolling(self.window).sum()
        dev = (close / vwap) - 1
        return dev

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
