from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class IdiosyncraticVolatility(FactorBase):
    """
    Idiosyncratic volatility: rolling std of residuals from regressing returns on market (mktrf).
    """

    def __init__(self, window: int = 60, min_periods: int | None = None, name: str | None = None):
        self.window = window
        self.min_periods = min_periods if min_periods is not None else max(20, window // 3)
        self.name = name or f"ivol_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        ff = data_loader.load_ff_factors()
        if "mktrf" not in ff.columns:
            raise ValueError("FF factors missing mktrf for idiosyncratic volatility")
        mkt = ff["mktrf"].reindex(rets.index)

        mkt_mean = mkt.rolling(self.window, min_periods=self.min_periods).mean()
        ret_mean = rets.rolling(self.window, min_periods=self.min_periods).mean()
        mkt_center = mkt - mkt_mean
        ret_center = rets - ret_mean
        cov = (ret_center.mul(mkt_center, axis=0)).rolling(self.window, min_periods=self.min_periods).mean()
        var_mkt = (mkt_center**2).rolling(self.window, min_periods=self.min_periods).mean()
        beta = cov.div(var_mkt, axis=0)

        residual = rets - beta.mul(mkt, axis=0)
        ivol = residual.rolling(self.window, min_periods=self.min_periods).std()
        return ivol

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
