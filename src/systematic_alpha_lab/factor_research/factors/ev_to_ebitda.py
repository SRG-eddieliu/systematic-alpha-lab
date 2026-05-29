from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase, factor_setting


class EVToEBITDA(FactorBase):
    """
    EV/EBITDA inverse using quarterly fundamentals (no annual fallback).
    EV = price * shares + total debt - cash.
    EBITDA ≈ operatingIncome + depreciationAndAmortization (or depreciation).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "ev_to_ebitda_inv"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        prices = data_loader.load_price_wide(dataset="price_daily")

        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        for df, nm in ((inc, "income_statement"), (bal, "balance_sheet")):
            if "period_type" not in df.columns:
                raise ValueError(f"fundamentals_{nm} missing period_type")
        inc = inc[inc["period_type"] == "quarterly"]
        bal = bal[bal["period_type"] == "quarterly"]

        inc["fiscalDateEnding"] = pd.to_datetime(inc["fiscalDateEnding"], errors="coerce").dt.date
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date

        # EBITDA proxy
        inc = inc[["ticker", "fiscalDateEnding", "operatingIncome", "depreciationAndAmortization", "depreciation"]].copy()
        inc["operatingIncome"] = pd.to_numeric(inc["operatingIncome"], errors="coerce")
        inc["depreciationAndAmortization"] = pd.to_numeric(inc["depreciationAndAmortization"], errors="coerce")
        inc["depreciation"] = pd.to_numeric(inc["depreciation"], errors="coerce")
        inc["ebitda"] = inc["operatingIncome"] + inc[["depreciationAndAmortization", "depreciation"]].sum(axis=1, min_count=1)
        inc = (
            inc.groupby(["ticker", "fiscalDateEnding"], as_index=False)["ebitda"]
            .mean()
            .dropna(subset=["ebitda"])
        )

        # Shares and debt/cash
        col_shares = "commonStockSharesOutstanding"
        for col in (col_shares, "shortLongTermDebtTotal", "shortTermDebt", "longTermDebt", "cashAndCashEquivalentsAtCarryingValue"):
            if col not in bal.columns:
                bal[col] = np.nan
        bal[col_shares] = pd.to_numeric(bal[col_shares], errors="coerce")
        bal["cash"] = pd.to_numeric(bal["cashAndCashEquivalentsAtCarryingValue"], errors="coerce")
        bal["debt_total"] = pd.to_numeric(bal["shortLongTermDebtTotal"], errors="coerce")
        # fallback debt if total missing
        missing_total = bal["debt_total"].isna()
        bal.loc[missing_total, "debt_total"] = (
            pd.to_numeric(bal["shortTermDebt"], errors="coerce")
            + pd.to_numeric(bal["longTermDebt"], errors="coerce")
        )
        bal = bal[["ticker", "fiscalDateEnding", col_shares, "cash", "debt_total"]]
        bal = bal.groupby(["ticker", "fiscalDateEnding"], as_index=False).mean()
        bal = bal.dropna(subset=[col_shares])

        # Pivot to wide
        ebitda = inc.pivot(index="fiscalDateEnding", columns="ticker", values="ebitda").sort_index()
        shares = bal.pivot(index="fiscalDateEnding", columns="ticker", values=col_shares).sort_index()
        cash = bal.pivot(index="fiscalDateEnding", columns="ticker", values="cash").sort_index()
        debt = bal.pivot(index="fiscalDateEnding", columns="ticker", values="debt_total").sort_index()

        # Align to price calendar and ffill
        ebitda = ebitda.reindex(prices.index).ffill()
        shares = shares.reindex(prices.index).ffill()
        cash = cash.reindex(prices.index).ffill()
        debt = debt.reindex(prices.index).ffill()

        tickers = prices.columns.intersection(shares.columns).intersection(ebitda.columns)
        price = prices[tickers]
        sh = shares[tickers]
        ca = cash.reindex(price.index).reindex(columns=tickers)
        db = debt.reindex(price.index).reindex(columns=tickers)

        ev = price * sh + db - ca
        ev_to_ebitda = ev / ebitda[tickers]
        inv = 1.0 / ev_to_ebitda.replace(0, np.nan)

        ff = factor_setting(getattr(self, "name", "ev_to_ebitda_inv"), self.__class__.__name__, "forward_fill", True)
        if ff:
            inv = inv.ffill()
        return inv

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
