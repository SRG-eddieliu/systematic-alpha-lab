from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class NetIssuance(FactorBase):
    """
    Net share issuance: percent change in shares outstanding over a lookback window (annual data), forward-fill configurable.
    """

    def __init__(self, name: str | None = None, window_years: int = 1):
        self.name = name or "net_issuance"
        self.window_years = window_years

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" in bal.columns:
            bal = bal[bal["period_type"] == "annual"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        shares_col = "commonStockSharesOutstanding"
        if shares_col not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing commonStockSharesOutstanding")
        bal["shares"] = pd.to_numeric(bal[shares_col], errors="coerce")
        bal = bal.dropna(subset=["fiscalDateEnding", "shares"])
        bal = bal.sort_values(["ticker", "fiscalDateEnding"])
        bal = bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)["shares"].mean()
        bal["net_issuance"] = bal.groupby("ticker")["shares"].pct_change(periods=self.window_years)
        df = bal.pivot(index="fiscalDateEnding", columns="ticker", values="net_issuance").sort_index()

        ff = factor_setting(getattr(self, "name", "net_issuance"), self.__class__.__name__, "forward_fill", True)
        if ff:
            price_index = data_loader.load_price_wide(dataset="price_daily").index
            df = df.reindex(price_index).ffill()
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
