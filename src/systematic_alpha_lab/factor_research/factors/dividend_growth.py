from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class DividendGrowth(FactorBase):
    """
    Dividend growth rate: pct change in trailing dividends (annual), forward-fill configurable.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "dividend_growth"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        div = data_loader.load_long(dataset="fundamentals_dividends")
        div["ex_dividend_date"] = pd.to_datetime(div["ex_dividend_date"], errors="coerce").dt.date
        div["amount"] = pd.to_numeric(div["amount"], errors="coerce")
        # Aggregate annual dividend per ticker
        div["year"] = pd.to_datetime(div["ex_dividend_date"]).dt.year
        annual = div.groupby(["ticker", "year"], as_index=False)["amount"].sum()
        annual = annual.sort_values(["ticker", "year"])
        annual["div_growth"] = annual.groupby("ticker")["amount"].pct_change()
        # Use year-end as date index
        annual["date"] = pd.to_datetime(annual["year"].astype(str) + "-12-31").dt.date
        df = annual.pivot(index="date", columns="ticker", values="div_growth").sort_index()

        ff = factor_setting(getattr(self, "name", "dividend_growth"), self.__class__.__name__, "forward_fill", True)
        if ff:
            price_index = data_loader.load_price_wide(dataset="price_daily").index
            df = df.reindex(price_index).ffill()
        return df

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
