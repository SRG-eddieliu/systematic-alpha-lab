from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

import pandas as pd

from .paths import final_dataset_path


def get_final_data(
    dataset: str = "price_daily",
    tickers: Optional[Iterable[str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """
    Load a final dataset with optional filtering (default: price_daily).
    """
    df = pd.read_parquet(final_dataset_path(dataset))
    # Apply common filters when columns exist
    if tickers and "ticker" in df.columns:
        df = df[df["ticker"].isin(set(tickers))]
    date_col = None
    for c in ["date", "Date"]:
        if c in df.columns:
            date_col = c
            break
    if date_col:
        if start_date:
            df = df[df[date_col] >= pd.to_datetime(start_date).date()]
        if end_date:
            df = df[df[date_col] <= pd.to_datetime(end_date).date()]
    return df.reset_index(drop=True)
