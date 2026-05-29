from __future__ import annotations

import pandas as pd
from ..base import FactorBase


class DividendYield(FactorBase):
    """
    Dividend yield: trailing 12-month dividends / price using dividend history (no company overview).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "dividend_yield_ttm"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        div = data_loader.load_long(dataset="fundamentals_dividends")
        div["ex_dividend_date"] = pd.to_datetime(div["ex_dividend_date"], errors="coerce").dt.date
        div["amount"] = pd.to_numeric(div["amount"], errors="coerce")
        div = div.dropna(subset=["ticker", "ex_dividend_date", "amount"])
        div_wide = div.pivot(index="ex_dividend_date", columns="ticker", values="amount").sort_index()

        prices = data_loader.load_price_wide(dataset="price_daily")
        div_wide = div_wide.reindex(prices.index, fill_value=0.0)
        # Trailing 12-month (approx 252 trading days) dividend sum
        trailing_div = div_wide.rolling(window=252, min_periods=1).sum()
        dy = trailing_div / prices
        return dy

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
