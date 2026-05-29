from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase, factor_setting


def _log_series(df: pd.DataFrame) -> pd.DataFrame:
    return np.log(df.replace(0, np.nan).abs())


class LogTotalAssets(FactorBase):
    """
    Log total assets (quarterly), forward-filled to daily.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "size_log_total_assets"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" in bal.columns:
            bal = bal[bal["period_type"] == "quarterly"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        if "totalAssets" not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing totalAssets")
        bal["totalAssets"] = pd.to_numeric(bal["totalAssets"], errors="coerce")
        bal = bal.dropna(subset=["ticker", "fiscalDateEnding", "totalAssets"])
        bal = bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)["totalAssets"].mean()
        assets = bal.pivot(index="fiscalDateEnding", columns="ticker", values="totalAssets").sort_index()
        assets = assets.reindex(prices.index).ffill()
        out = _log_series(assets)
        ff = factor_setting(getattr(self, "name", "size_log_total_assets"), self.__class__.__name__, "forward_fill", True)
        if ff:
            out = out.ffill()
        return out

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)


class LogEnterpriseValue(FactorBase):
    """
    Log enterprise value (price*shares + debt - cash), quarterly inputs, forward-filled to daily.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "size_log_enterprise_value"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" in bal.columns:
            bal = bal[bal["period_type"] == "quarterly"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        for col in (
            "commonStockSharesOutstanding",
            "shortLongTermDebtTotal",
            "shortTermDebt",
            "longTermDebt",
            "cashAndCashEquivalentsAtCarryingValue",
        ):
            if col not in bal.columns:
                bal[col] = np.nan
        bal["commonStockSharesOutstanding"] = pd.to_numeric(
            bal["commonStockSharesOutstanding"], errors="coerce"
        )
        bal["cash"] = pd.to_numeric(bal["cashAndCashEquivalentsAtCarryingValue"], errors="coerce")
        bal["debt_total"] = pd.to_numeric(bal["shortLongTermDebtTotal"], errors="coerce")
        missing_total = bal["debt_total"].isna()
        bal.loc[missing_total, "debt_total"] = (
            pd.to_numeric(bal["shortTermDebt"], errors="coerce")
            + pd.to_numeric(bal["longTermDebt"], errors="coerce")
        )
        bal = bal[["ticker", "fiscalDateEnding", "commonStockSharesOutstanding", "cash", "debt_total"]]
        bal = bal.groupby(["ticker", "fiscalDateEnding"], as_index=False).mean()
        bal = bal.dropna(subset=["commonStockSharesOutstanding"])

        shares = bal.pivot(index="fiscalDateEnding", columns="ticker", values="commonStockSharesOutstanding").sort_index()
        cash = bal.pivot(index="fiscalDateEnding", columns="ticker", values="cash").sort_index()
        debt = bal.pivot(index="fiscalDateEnding", columns="ticker", values="debt_total").sort_index()

        shares = shares.reindex(prices.index).ffill()
        cash = cash.reindex(prices.index).ffill()
        debt = debt.reindex(prices.index).ffill()

        tickers = prices.columns.intersection(shares.columns)
        price = prices[tickers]
        sh = shares[tickers]
        ca = cash.reindex(price.index).reindex(columns=tickers)
        db = debt.reindex(price.index).reindex(columns=tickers)
        ev = price * sh + db - ca
        out = _log_series(ev)
        ff = factor_setting(getattr(self, "name", "size_log_enterprise_value"), self.__class__.__name__, "forward_fill", True)
        if ff:
            out = out.ffill()
        return out

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)


class LogRevenue(FactorBase):
    """
    Log total revenue (quarterly), forward-filled to daily.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "size_log_revenue"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        if "period_type" in inc.columns:
            inc = inc[inc["period_type"] == "quarterly"]
        inc["fiscalDateEnding"] = pd.to_datetime(inc["fiscalDateEnding"], errors="coerce").dt.date
        if "totalRevenue" not in inc.columns:
            raise ValueError("fundamentals_income_statement missing totalRevenue")
        inc["totalRevenue"] = pd.to_numeric(inc["totalRevenue"], errors="coerce")
        inc = inc.dropna(subset=["ticker", "fiscalDateEnding", "totalRevenue"])
        inc = inc.groupby(["ticker", "fiscalDateEnding"], as_index=False)["totalRevenue"].mean()
        rev = inc.pivot(index="fiscalDateEnding", columns="ticker", values="totalRevenue").sort_index()
        rev = rev.reindex(prices.index).ffill()
        out = _log_series(rev)
        ff = factor_setting(getattr(self, "name", "size_log_revenue"), self.__class__.__name__, "forward_fill", True)
        if ff:
            out = out.ffill()
        return out

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
