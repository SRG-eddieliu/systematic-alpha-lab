from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class StandardizedUnexpectedEarnings(FactorBase):
    """
    SUE: (reported EPS - estimated EPS) standardized by rolling std over past quarters.
    Quarterly only; no annual fallback.
    """

    def __init__(self, name: str | None = None, window_quarters: int = 8):
        self.name = name or "sue"
        self.window_quarters = window_quarters

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        df = data_loader.load_long(dataset="fundamentals_earnings")
        if "period_type" in df.columns:
            df = df[df["period_type"] == "quarterly"]
        dt = pd.to_datetime(df.get("reportedDate", df.get("fiscalDateEnding")), errors="coerce")
        df["date"] = (dt + pd.tseries.offsets.BusinessDay(2)).dt.date
        df["reportedEPS"] = pd.to_numeric(df["reportedEPS"], errors="coerce")
        df["estimatedEPS"] = pd.to_numeric(df["estimatedEPS"], errors="coerce")
        df = df.dropna(subset=["ticker", "date"])
        # Deduplicate ticker/date by averaging to avoid pivot collisions
        df = df.groupby(["ticker", "date"], as_index=False)[["reportedEPS", "estimatedEPS"]].mean()
        df = df.sort_values(["ticker", "date"])
        df["surprise"] = df["reportedEPS"] - df["estimatedEPS"]
        df["std_surprise"] = df.groupby("ticker")["surprise"].rolling(self.window_quarters, min_periods=2).std().reset_index(level=0, drop=True)
        df["sue"] = df["surprise"] / df["std_surprise"]
        sue = df.pivot(index="date", columns="ticker", values="sue").sort_index()
        prices = data_loader.load_price_wide(dataset="price_daily")
        sue = sue.reindex(prices.index).ffill()
        ff = factor_setting(getattr(self, "name", "sue"), self.__class__.__name__, "forward_fill", True)
        if ff:
            sue = sue.ffill()
        return sue

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
