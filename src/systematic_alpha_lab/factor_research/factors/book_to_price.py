from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class BookToPrice(FactorBase):
    """
    Book-to-price: book value per share (annual) divided by price.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "book_to_price"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing period_type")
        bal = bal[bal["period_type"] == "annual"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date
        for col in ["totalShareholderEquity", "commonStockSharesOutstanding"]:
            if col not in bal.columns:
                raise ValueError(f"fundamentals_balance_sheet missing {col}")
            bal[col] = pd.to_numeric(bal[col], errors="coerce")
        bal = bal.dropna(subset=["totalShareholderEquity", "commonStockSharesOutstanding"])
        bal = bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)[
            ["totalShareholderEquity", "commonStockSharesOutstanding"]
        ].mean()
        bal["book_per_share"] = bal["totalShareholderEquity"] / bal["commonStockSharesOutstanding"]
        bps = bal.pivot(index="fiscalDateEnding", columns="ticker", values="book_per_share").sort_index()

        prices = data_loader.load_price_wide(dataset="price_daily")
        bps = bps.reindex(prices.index).ffill()
        tickers = prices.columns.intersection(bps.columns)
        btp = bps[tickers] / prices[tickers]
        return btp

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
