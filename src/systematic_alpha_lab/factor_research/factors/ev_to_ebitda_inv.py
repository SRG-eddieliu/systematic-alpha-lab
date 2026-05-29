from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class EVtoEBITDAInv(FactorBase):
    """
    Inverse of EV/EBITDA from company overview, broadcast across dates.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "ev_to_ebitda_inv"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        df = data_loader.load_long(dataset="company_overview")
        if "ticker" not in df.columns and "Symbol" in df.columns:
            df = df.rename(columns={"Symbol": "ticker"})
        if "EVToEBITDA" not in df.columns:
            raise ValueError("company_overview missing EVToEBITDA")
        inv = 1.0 / pd.to_numeric(df.set_index("ticker")["EVToEBITDA"], errors="coerce").replace(0, pd.NA)
        inv = inv.dropna()
        prices = data_loader.load_price_wide(dataset="price_daily")
        cols = prices.columns.intersection(inv.index)
        const = inv.loc[cols]
        seed = pd.DataFrame([const], index=[prices.index.min()])
        df_out = seed.reindex(prices.index, method="ffill")[cols]
        return df_out

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
