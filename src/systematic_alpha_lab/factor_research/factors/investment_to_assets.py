from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class InvestmentToAssets(FactorBase):
    """
    Investment-to-assets: change in (PPE + inventory) over 4 quarters scaled by total assets (quarterly only).
    """

    def __init__(self, name: str | None = None):
        self.name = name or "investment_to_assets"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        bal = data_loader.load_long(dataset="fundamentals_balance_sheet")
        if "period_type" not in bal.columns:
            raise ValueError("fundamentals_balance_sheet missing period_type")
        bal = bal[bal["period_type"] == "quarterly"]
        bal["fiscalDateEnding"] = pd.to_datetime(bal["fiscalDateEnding"], errors="coerce").dt.date

        for col in ["propertyPlantEquipment", "inventory", "totalAssets"]:
            if col not in bal.columns:
                raise ValueError(f"fundamentals_balance_sheet missing {col}")
            bal[col] = pd.to_numeric(bal[col], errors="coerce")

        bal = (
            bal.groupby(["ticker", "fiscalDateEnding"], as_index=False)[
                ["propertyPlantEquipment", "inventory", "totalAssets"]
            ]
            .mean()
            .sort_values(["ticker", "fiscalDateEnding"])
        )
        bal["ppe_inv"] = bal["propertyPlantEquipment"].fillna(0) + bal["inventory"].fillna(0)
        bal["ppe_inv_prev"] = bal.groupby("ticker")["ppe_inv"].shift(4)
        bal["inv_to_assets"] = (bal["ppe_inv"] - bal["ppe_inv_prev"]) / bal["totalAssets"]

        fac = bal.pivot(index="fiscalDateEnding", columns="ticker", values="inv_to_assets").sort_index()
        prices = data_loader.load_price_wide(dataset="price_daily")
        fac = fac.reindex(prices.index).ffill()
        ff = factor_setting(getattr(self, "name", "investment_to_assets"), self.__class__.__name__, "forward_fill", True)
        if ff:
            fac = fac.ffill()
        return fac

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)
