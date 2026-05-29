from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase


class AverageTrueRange(FactorBase):
    """
    Average True Range: rolling mean of true range (volatility proxy), shifted one day.
    """

    def __init__(self, window: int = 14, name: str | None = None):
        self.window = window
        self.name = name or f"atr_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_long(dataset="price_daily")
        prices["date"] = pd.to_datetime(prices["date"]).dt.date
        hi = prices.pivot(index="date", columns="ticker", values="high").sort_index()
        lo = prices.pivot(index="date", columns="ticker", values="low").sort_index()
        close = prices.pivot(index="date", columns="ticker", values="adjusted_close").sort_index()
        prev_close = close.shift(1)
        # Elementwise max across the three true-range components
        tr_components = [
            (hi - lo).values,
            (hi - prev_close).abs().values,
            (lo - prev_close).abs().values,
        ]
        tr = pd.DataFrame(
            np.maximum.reduce(tr_components),
            index=hi.index,
            columns=hi.columns,
        )
        atr = tr.rolling(self.window).mean()
        return atr

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
