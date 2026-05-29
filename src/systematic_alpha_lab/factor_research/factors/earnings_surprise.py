from __future__ import annotations

import pandas as pd

from ..base import FactorBase


class EarningsSurprise(FactorBase):
    """
    Earnings surprise percentage from earnings dataset, pivoted by reportedDate.
    """

    def __init__(self, name: str | None = None):
        self.name = name or "earnings_surprise"

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        # Prefer quarterly-only dataset; fallback to combined and filter quarterly if present.
        try:
            df = data_loader.load_long(dataset="fundamentals_earnings_quarterly")
        except Exception:
            df = data_loader.load_long(dataset="fundamentals_earnings")

        # If period_type exists, keep quarterly rows to avoid sparse annual data.
        if "period_type" in df.columns:
            df = df[df["period_type"] == "quarterly"]

        date_col = "reportedDate" if "reportedDate" in df.columns else "fiscalDateEnding"
        dt = pd.to_datetime(df[date_col], errors="coerce")
        # Lag by 2 business days to reduce look-ahead
        df["date"] = (dt + pd.tseries.offsets.BusinessDay(2)).dt.date
        surprise = pd.to_numeric(df.get("surprisePercentage", pd.NA), errors="coerce")
        df["surprise_pct"] = surprise
        agg = (
            df.groupby(["date", "ticker"])["surprise_pct"]
            .mean()
            .unstack()
            .sort_index()
        )
        return agg

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(1)

    def compute(
        self,
        data_loader,
        sector_map=None,
        winsor_limits: tuple[float, float] = (0.01, 0.99),
        min_coverage: float = 0.0,
        fill_method: str | None = None,
        neutralize_method: str = "sector",
    ) -> pd.DataFrame:
        """
        Override to relax coverage (sparse event data) and avoid filling sparse surprises.
        """
        return super().compute(
            data_loader,
            sector_map=sector_map,
            winsor_limits=winsor_limits,
            min_coverage=min_coverage,
            fill_method=fill_method,
            neutralize_method=neutralize_method,
        )
