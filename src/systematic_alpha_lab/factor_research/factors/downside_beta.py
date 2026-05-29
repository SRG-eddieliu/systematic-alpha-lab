from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class DownsideBeta(FactorBase):
    """
    Downside beta: rolling beta to market using only down-market days.
    """

    def __init__(self, window: int = 252, min_periods: int | None = None, name: str | None = None):
        self.window = window
        self.min_periods = min_periods if min_periods is not None else max(60, window // 3)
        self.name = name or f"downside_beta_{window}d"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        rets = prices.pct_change()
        ff = data_loader.load_ff_factors()
        if "mktrf" not in ff.columns:
            raise ValueError("FF factors missing mktrf for downside beta")
        mkt = ff["mktrf"].reindex(rets.index)
        mask = mkt < 0
        mkt_neg = mkt.where(mask)
        # Align mask by rows (dates); DataFrame.where with axis=0 broadcasts over columns
        rets_neg = rets.where(mask, axis=0)

        mkt_mean = mkt_neg.rolling(self.window, min_periods=self.min_periods).mean()
        ret_mean = rets_neg.rolling(self.window, min_periods=self.min_periods).mean()
        mkt_center = mkt_neg - mkt_mean
        ret_center = rets_neg - ret_mean
        cov = (ret_center.mul(mkt_center, axis=0)).rolling(self.window, min_periods=self.min_periods).mean()
        var_mkt = (mkt_center ** 2).rolling(self.window, min_periods=self.min_periods).mean()
        beta = cov.div(var_mkt, axis=0)
        return beta

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
