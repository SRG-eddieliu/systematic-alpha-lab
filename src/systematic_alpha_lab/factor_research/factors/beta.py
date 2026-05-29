from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class Beta(FactorBase):
    """
    Rolling beta to market (uses FF mktrf) over a specified window.
    """

    def __init__(self, window: int = 252, min_periods: int | None = None, name: str | None = None):
        self.window = window
        self.min_periods = min_periods if min_periods is not None else max(60, window // 3)
        self.name = name or f"beta_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        ff = data_loader.load_ff_factors()
        if "mktrf" not in ff.columns:
            raise ValueError("FF factors missing mktrf for beta computation")
        mkt = ff["mktrf"].reindex(rets.index)
        # center
        mkt_mean = mkt.rolling(self.window, min_periods=self.min_periods).mean()
        mkt_center = mkt - mkt_mean
        ret_mean = rets.rolling(self.window, min_periods=self.min_periods).mean()
        ret_center = rets - ret_mean
        cov = (ret_center.mul(mkt_center, axis=0)).rolling(self.window, min_periods=self.min_periods).mean()
        var_mkt = (mkt_center ** 2).rolling(self.window, min_periods=self.min_periods).mean()
        beta = cov.div(var_mkt, axis=0)
        return beta

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
