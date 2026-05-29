from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class Coskewness(FactorBase):
    """
    Coskewness: beta to squared market returns over a rolling window.
    """

    def __init__(self, window: int = 252, min_periods: int | None = None, name: str | None = None):
        self.window = window
        self.min_periods = min_periods if min_periods is not None else max(60, window // 4)
        self.name = name or f"coskewness_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        ff = data_loader.load_ff_factors()
        if "mktrf" not in ff.columns:
            raise ValueError("FF factors missing mktrf for coskewness")
        mkt = ff["mktrf"].reindex(rets.index)
        m2 = mkt ** 2
        m2_mean = m2.rolling(self.window, min_periods=self.min_periods).mean()
        m2_center = m2 - m2_mean

        ret_mean = rets.rolling(self.window, min_periods=self.min_periods).mean()
        ret_center = rets - ret_mean

        cov = (ret_center.mul(m2_center, axis=0)).rolling(self.window, min_periods=self.min_periods).mean()
        var_m2 = (m2_center**2).rolling(self.window, min_periods=self.min_periods).mean()
        beta_coskew = cov.div(var_m2, axis=0)
        return beta_coskew

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
