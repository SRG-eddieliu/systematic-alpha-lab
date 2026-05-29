from __future__ import annotations

import pandas as pd

from ..base import FactorBase, factor_setting


class AnalystRevision(FactorBase):
    """
    Analyst EPS estimate revisions: up minus down over trailing 30 days.
    """

    def __init__(self, name: str | None = None, lag_days: int | None = None):
        self.name = name or "analyst_revision_eps_30d"
        # Allow config override; default to 1-day lag to avoid look-ahead
        self.lag_days = lag_days or factor_setting(self.name, self.__class__.__name__, "lag_days", default=1)

    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        df = data_loader.load_long(dataset="fundamentals_earnings_estimates")
        df["date"] = pd.to_datetime(df["date"]).dt.date
        up = pd.to_numeric(df["eps_estimate_revision_up_trailing_30_days"], errors="coerce").fillna(0.0)
        down = pd.to_numeric(df["eps_estimate_revision_down_trailing_30_days"], errors="coerce").fillna(0.0)
        df["revision"] = up - down
        wide = df.pivot(index="date", columns="ticker", values="revision").sort_index()
        # Reindex to price calendar to avoid sparse quarterly-only dates
        price_idx = data_loader.load_price_wide(dataset="price_daily").index
        # Carry forward within the 30-day window to avoid stale signals lingering indefinitely.
        wide = wide.reindex(price_idx).ffill(limit=30)
        return wide

    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        return raw_factor.shift(self.lag_days)
