from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class FreeCashflowYield(FactorBase):
    """
    Free cashflow yield: (operatingCashflow - capex) / market cap using annual fundamentals + price × shares, forward-fill configurable.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "free_cashflow_yield"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        cf = data_loader.load_long(dataset="fundamentals_cash_flow")
        if "period_type" not in cf.columns:
            raise ValueError("fundamentals_cash_flow missing period_type")
        cf = cf[cf["period_type"] == "annual"]
        cf["fiscalDateEnding"] = pd.to_datetime(cf["fiscalDateEnding"], errors="coerce").dt.date
        cf["operatingCashflow"] = pd.to_numeric(cf["operatingCashflow"], errors="coerce")
        cf["capitalExpenditures"] = pd.to_numeric(cf["capitalExpenditures"], errors="coerce")
        cf = cf.groupby(["ticker", "fiscalDateEnding"], as_index=False)[["operatingCashflow", "capitalExpenditures"]].mean()
        cf["fcf"] = cf["operatingCashflow"] - cf["capitalExpenditures"]

        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing period_type")
        bal = bal[bal["period_type"] == "annual"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        col = "commonStockSharesOutstanding"
        if col not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing commonStockSharesOutstanding")
        bal[col] = pd.to_numeric(bal[col], errors="coerce")
        shares = (
            bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)[col]
            .mean()
            .pivot(index="fiscalDateEnding", columns="ticker", values=col)
            .sort_index()
        )

        prices = data_loader.load_price_wide(dataset="price_daily")
        shares = shares.reindex(prices.index).ffill()
        tickers = prices.columns.intersection(shares.columns)

        fcf_wide = cf.pivot(index="fiscalDateEnding", columns="ticker", values="fcf").sort_index()
        fcf_wide = fcf_wide.reindex(prices.index).ffill()
        fcf_wide = fcf_wide[tickers]
        cap = prices[tickers] * shares[tickers]
        fcf_yield = fcf_wide / cap.replace(0, pd.NA)

        ff = factor_setting(getattr(self, "name", "free_cashflow_yield"), self.__class__.__name__, "forward_fill", True)
        if ff:
            fcf_yield = fcf_yield.ffill()
        return fcf_yield

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
