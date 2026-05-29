from __future__ import annotations

import pandas as pd
from ..base import FactorBase, factor_setting


class EarningsYield(FactorBase):
    """
    Earnings yield: trailing earnings (TTM) divided by market cap, forward-filled between reports.
    """

    def __init__(self, name: str | None = None, use_quarterly: bool = True):
        self.name = name or "earnings_yield"
        self.use_quarterly = use_quarterly

    @staticmethod
    def _prepare_income(data_loader, use_quarterly: bool) -> pd.DataFrame:
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        if "period_type" in inc.columns:
            pref = "quarterly" if use_quarterly else "annual"
            inc = inc[inc["period_type"] == pref]
        inc["fiscalDateEnding"] = pd.to_datetime(inc["fiscalDateEnding"], errors="coerce").dt.date
        inc = inc[["ticker", "fiscalDateEnding", "netIncome"]].copy()
        inc["netIncome"] = pd.to_numeric(inc["netIncome"], errors="coerce")
        inc = inc.dropna(subset=["ticker", "fiscalDateEnding", "netIncome"])
        inc = inc.groupby(["ticker", "fiscalDateEnding"], as_index=False)["netIncome"].mean()
        return inc

    @staticmethod
    def _prepare_shares(data_loader, use_quarterly: bool) -> pd.DataFrame:
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" in bal.columns:
            pref = "quarterly" if use_quarterly else "annual"
            bal = bal[bal["period_type"] == pref]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        col = "commonStockSharesOutstanding"
        if col not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing commonStockSharesOutstanding")
        bal = bal[["ticker", "fiscalDateEnding", col]].copy()
        bal[col] = pd.to_numeric(bal[col], errors="coerce")
        bal = bal.dropna(subset=["ticker", "fiscalDateEnding", col])
        bal = bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)[col].mean()
        bal = bal.rename(columns={col: "shares"})
        return bal

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")

        inc = self._prepare_income(data_loader, self.use_quarterly)
        bal = self._prepare_shares(data_loader, self.use_quarterly)

        if self.use_quarterly:
            # Compute TTM per ticker before pivot to avoid cross-firm sparse rolling
            inc = inc.sort_values(["ticker", "fiscalDateEnding"])
            inc["netIncome_ttm"] = (
                inc.groupby("ticker")["netIncome"].rolling(4, min_periods=1).sum().reset_index(level=0, drop=True)
            )
            inc_pivot = inc.pivot(index="fiscalDateEnding", columns="ticker", values="netIncome_ttm").sort_index()
        else:
            inc_pivot = inc.pivot(index="fiscalDateEnding", columns="ticker", values="netIncome").sort_index()
        inc_ttm = inc_pivot

        shares_pivot = bal.pivot(index="fiscalDateEnding", columns="ticker", values="shares").sort_index()

        # Reindex both to the price calendar and forward-fill between reports
        inc_ttm = inc_ttm.reindex(prices.index).ffill()
        shares_pivot = shares_pivot.reindex(prices.index).ffill()

        # Align tickers and compute market cap + earnings yield
        tickers = prices.columns.intersection(shares_pivot.columns).intersection(inc_ttm.columns)
        if tickers.empty:
            return pd.DataFrame(index=prices.index)
        cap = prices[tickers] * shares_pivot[tickers]
        ey = inc_ttm[tickers] / cap.replace(0, pd.NA)

        # Optional additional forward-fill controlled via config
        ff = factor_setting(getattr(self, "name", "earnings_yield"), self.__class__.__name__, "forward_fill", True)
        if ff:
            ey = ey.ffill()
        return ey

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
