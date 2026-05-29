from __future__ import annotations

import numpy as np
import pandas as pd

from ..base import FactorBase, factor_setting


class PiotroskiFScore(FactorBase):
    """
    Piotroski F-Score (0-9) using quarterly fundamentals (no annual fallback).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "piotroski_fscore"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        inc = data_loader.load_long(dataset="fundamentals_income_statement")
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        cf = data_loader.load_long(dataset="fundamentals_cash_flow")
        for df, nm in ((inc, "income_statement"), (bal, "balance_sheet"), (cf, "cash_flow")):
            if "period_type" not in df.columns:
                raise ValueError(f"fundamentals_{nm} missing period_type")
        inc = inc[inc["period_type"] == "quarterly"]
        bal = bal[bal["period_type"] == "quarterly"]
        cf = cf[cf["period_type"] == "quarterly"]

        for df in (inc, bal, cf):
            df["fiscalDateEnding"] = pd.to_datetime(df["fiscalDateEnding"], errors="coerce").dt.date

        # Select and numeric convert
        inc = inc[
            ["ticker", "fiscalDateEnding", "netIncome", "totalRevenue", "grossProfit"]
        ].copy()
        inc = inc.apply(pd.to_numeric, errors="ignore")
        inc["netIncome"] = pd.to_numeric(inc["netIncome"], errors="coerce")
        inc["totalRevenue"] = pd.to_numeric(inc["totalRevenue"], errors="coerce")
        inc["grossProfit"] = pd.to_numeric(inc["grossProfit"], errors="coerce")
        inc = inc.groupby(["ticker", "fiscalDateEnding"], as_index=False).mean()

        bal = bal[
            [
                "ticker",
                "fiscalDateEnding",
                "totalAssets",
                "totalCurrentAssets",
                "totalCurrentLiabilities",
                "longTermDebt",
                "totalShareholderEquity",
                "commonStockSharesOutstanding",
            ]
        ].copy()
        for col in bal.columns:
            if col not in ["ticker", "fiscalDateEnding"]:
                bal[col] = pd.to_numeric(bal[col], errors="coerce")
        bal = bal.groupby(["ticker", "fiscalDateEnding"], as_index=False).mean()

        cf = cf[["ticker", "fiscalDateEnding", "operatingCashflow"]].copy()
        cf["operatingCashflow"] = pd.to_numeric(cf["operatingCashflow"], errors="coerce")
        cf = cf.groupby(["ticker", "fiscalDateEnding"], as_index=False).mean()

        # Merge
        df = inc.merge(bal, on=["ticker", "fiscalDateEnding"], how="left").merge(
            cf, on=["ticker", "fiscalDateEnding"], how="left"
        )
        df = df.sort_values(["ticker", "fiscalDateEnding"])

        # Compute components
        df["roa"] = df["netIncome"] / df["totalAssets"]
        df["roa_prev"] = df.groupby("ticker")["roa"].shift(4)
        df["cfo"] = df["operatingCashflow"] / df["totalAssets"]
        df["accrual"] = df["cfo"] - df["roa"]

        df["longTermDebt_prev"] = df.groupby("ticker")["longTermDebt"].shift(4)
        df["leverage_change"] = df["longTermDebt"] < df["longTermDebt_prev"]

        df["curr_ratio"] = df["totalCurrentAssets"] / df["totalCurrentLiabilities"]
        df["curr_ratio_prev"] = df.groupby("ticker")["curr_ratio"].shift(4)
        df["curr_ratio_change"] = df["curr_ratio"] > df["curr_ratio_prev"]

        df["shares_prev"] = df.groupby("ticker")["commonStockSharesOutstanding"].shift(4)
        df["no_dilution"] = df["commonStockSharesOutstanding"] <= df["shares_prev"]

        df["gross_margin"] = df["grossProfit"] / df["totalRevenue"]
        df["gross_margin_prev"] = df.groupby("ticker")["gross_margin"].shift(4)
        df["gm_change"] = df["gross_margin"] > df["gross_margin_prev"]

        df["asset_turnover"] = df["totalRevenue"] / df["totalAssets"]
        df["asset_turnover_prev"] = df.groupby("ticker")["asset_turnover"].shift(4)
        df["at_change"] = df["asset_turnover"] > df["asset_turnover_prev"]

        # Flags
        flags = pd.DataFrame(
            {
                "roa_pos": df["roa"] > 0,
                "roa_improve": df["roa"] > df["roa_prev"],
                "cfo_pos": df["cfo"] > 0,
                "accrual": df["accrual"] > 0,
                "leverage": df["leverage_change"],
                "liquidity": df["curr_ratio_change"],
                "no_dilution": df["no_dilution"],
                "gm": df["gm_change"],
                "at": df["at_change"],
            }
        ).astype(float)

        df["fscore"] = flags.sum(axis=1)

        fscore = df.pivot(index="fiscalDateEnding", columns="ticker", values="fscore").sort_index()
        prices = data_loader.load_price_wide(dataset="price_daily")
        fscore = fscore.reindex(prices.index).ffill()
        ff = factor_setting(getattr(self, "name", "piotroski_fscore"), self.__class__.__name__, "forward_fill", True)
        if ff:
            fscore = fscore.ffill()
        return fscore

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
