from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class AmihudIlliquidity(FactorBase):
    """
    Amihud illiquidity: rolling mean of |ret| / dollar_volume over a window.
    """

    def __init__(self, window: int = 20, name: str | None = None):
        self.window = window
        self.name = name or f"amihud_illiq_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        df = data_loader.load_long(dataset="price_daily")
        df["date"] = pd.to_datetime(df["date"]).dt.date
        price_col = "adjusted_close" if "adjusted_close" in df.columns else "close"
        price_wide = df.pivot(index="date", columns="ticker", values=price_col).sort_index()
        vol_wide = df.pivot(index="date", columns="ticker", values="volume").sort_index()
        rets = price_wide.pct_change()
        dollar_vol = price_wide * vol_wide
        illiq = (rets.abs() / dollar_vol).rolling(window=self.window, min_periods=max(5, self.window // 2)).mean()
        return illiq

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
