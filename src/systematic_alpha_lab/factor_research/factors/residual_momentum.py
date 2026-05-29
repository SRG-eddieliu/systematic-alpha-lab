from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class ResidualMomentum(FactorBase):
    """
    Residual momentum: 12m return (skip recent 1m) net of market component.
    """

    def __init__(
        self,
        lookback_days: int = 252,
        skip_days: int = 21,
        beta_window: int = 756,
        min_beta_periods: int | None = None,
        name: str | None = None,
    ):
        self.lookback_days = lookback_days
        self.skip_days = skip_days
        self.beta_window = beta_window
        self.min_beta_periods = min_beta_periods if min_beta_periods is not None else max(60, beta_window // 4)
        self.name = name or "residual_momentum_12m"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        ff = data_loader.load_ff_factors()
        if "mktrf" not in ff.columns:
            raise ValueError("FF factors missing mktrf for residual momentum")
        mkt = ff["mktrf"].reindex(rets.index)

        # rolling beta to market
        mkt_mean = mkt.rolling(self.beta_window, min_periods=self.min_beta_periods).mean()
        ret_mean = rets.rolling(self.beta_window, min_periods=self.min_beta_periods).mean()
        mkt_center = mkt - mkt_mean
        ret_center = rets - ret_mean
        cov = (ret_center.mul(mkt_center, axis=0)).rolling(self.beta_window, min_periods=self.min_beta_periods).mean()
        var_mkt = (mkt_center**2).rolling(self.beta_window, min_periods=self.min_beta_periods).mean()
        beta = cov.div(var_mkt, axis=0)

        residual_ret = rets - beta.mul(mkt, axis=0)
        # Exclude most recent month
        shifted = residual_ret.shift(self.skip_days)
        window = self.lookback_days - self.skip_days
        res_mom = shifted.rolling(window, min_periods=window // 2).sum()
        return res_mom

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
