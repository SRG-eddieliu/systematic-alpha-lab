from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional
from pathlib import Path

import pandas as pd

from .paths import final_data_dir


@dataclass
class DataLoader:
    """
    Loads cleaned long-format Parquets and pivots them to wide Date x Ticker frames.
    """

    data_dir: Optional[str] = None
    default_start_date: Optional[date] = None
    default_end_date: Optional[date] = None

    def _dataset_path(self, dataset: str) -> Path:
        base = final_data_dir() if self.data_dir is None else Path(self.data_dir)
        return base / f"{dataset}.parquet"

    def load_long(
        self,
        dataset: str = "price_daily",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        tickers: Optional[Iterable[str]] = None,
        clip_to_available: bool = True,
    ) -> pd.DataFrame:
        path = self._dataset_path(dataset)
        df = pd.read_parquet(path)
        # Apply defaults if explicit dates not supplied
        if start_date is None:
            start_date = self.default_start_date
        if end_date is None:
            end_date = self.default_end_date
        has_date = "date" in df.columns
        if has_date:
            df["date"] = pd.to_datetime(df["date"]).dt.date
            if clip_to_available and not df.empty:
                min_date, max_date = df["date"].min(), df["date"].max()
                if start_date and start_date < min_date:
                    start_date = min_date
                if end_date and end_date > max_date:
                    end_date = max_date
        if has_date and start_date:
            df = df[df["date"] >= start_date]
        if has_date and end_date:
            df = df[df["date"] <= end_date]
        if tickers is not None and "ticker" in df.columns:
            df = df[df["ticker"].isin(set(tickers))]
        return df

    def load_price_wide(
        self,
        dataset: str = "price_daily",
        value_col: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        tickers: Optional[Iterable[str]] = None,
        clip_to_available: bool = True,
    ) -> pd.DataFrame:
        df = self.load_long(
            dataset=dataset,
            start_date=start_date,
            end_date=end_date,
            tickers=tickers,
            clip_to_available=clip_to_available,
        )
        candidates = [value_col] if value_col else []
        candidates += ["adjusted_close", "close", "price"]
        col = next((c for c in candidates if c in df.columns), None)
        if col is None:
            raise ValueError(f"No price column found in {dataset}")
        wide = df.pivot(index="date", columns="ticker", values=col).sort_index()
        return wide

    def load_sector_map(self, dataset: str = "company_overview", sector_col: str = "Sector") -> pd.Series:
        df = self.load_long(dataset=dataset)
        if "ticker" not in df.columns or sector_col not in df.columns:
            raise ValueError("company_overview dataset missing ticker or sector column")
        return df.set_index("ticker")[sector_col].dropna()

    def forward_returns(self, price_wide: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
        """
        Compute forward returns over `horizon` days aligned to today (t) using future prices.
        """
        return price_wide.shift(-horizon) / price_wide - 1.0

    def load_ff_factors(self, path: Optional[Path] = None, scale_if_percent: bool = True) -> pd.DataFrame:
        """
        Load Fama-French factor time series (market, SMB, HML, etc.) from data-processed.
        Returns a DataFrame indexed by date with columns lowercased (mktrf, smb, hml, rmw, cma, rf, umd when present).
        If values look like percentages (abs max > 2), divide by 100 when scale_if_percent=True.
        """
        path = path or final_data_dir() / "FAMA_FRENCH_FACTORS.parquet"
        if not path.exists():
            raise FileNotFoundError(f"FF factors not found at {path}")
        df = pd.read_parquet(path)
        df.columns = [c.lower() for c in df.columns]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.set_index("date").sort_index()
        num_cols = df.select_dtypes(include="number").columns
        if scale_if_percent and len(num_cols) and df[num_cols].abs().max().max() > 2:
            df[num_cols] = df[num_cols] / 100.0
        return df
