from __future__ import annotations

import numpy as np
import pandas as pd


def winsorize(df: pd.DataFrame, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    """
    Clip extremes cross-sectionally by date.
    """
    def _clip(row: pd.Series) -> pd.Series:
        if row.dropna().empty:
            return row
        lo = row.quantile(lower)
        hi = row.quantile(upper)
        return row.clip(lower=lo, upper=hi)

    return df.apply(_clip, axis=1)


def zscore(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-sectional z-score per date.
    """
    def _z(row: pd.Series) -> pd.Series:
        mean = row.mean()
        std = row.std(ddof=0)
        if std == 0 or np.isnan(std):
            return pd.Series(np.nan, index=row.index)
        return (row - mean) / std

    return df.apply(_z, axis=1)


def sector_neutralize(df: pd.DataFrame, sector_map: pd.Series) -> pd.DataFrame:
    """
    Demean factor values within each sector group.
    """
    sector_map = sector_map.dropna()
    def _neutralize(row: pd.Series) -> pd.Series:
        if row.dropna().empty:
            return row
        aligned = row.reindex(sector_map.index)
        sectors = sector_map.loc[aligned.index]
        adjusted = aligned.copy()
        for sector, tickers in sectors.groupby(sectors).groups.items():
            vals = aligned.loc[tickers]
            if vals.dropna().empty:
                continue
            adjusted.loc[tickers] = vals - vals.mean()
        return adjusted.reindex(row.index)

    return df.apply(_neutralize, axis=1)


def coverage_filter(df: pd.DataFrame, min_coverage: float) -> pd.DataFrame:
    """Drop dates with cross-sectional coverage below threshold."""
    if not min_coverage:
        return df
    coverage = df.notna().mean(axis=1)
    return df.loc[coverage >= min_coverage]


def fill_factor(df: pd.DataFrame, method: str | None = "median", sector_map: pd.Series | None = None) -> pd.DataFrame:
    """
    Fill missing values cross-sectionally per date.
      - median: fill with cross-sectional median
      - sector_median: fill with within-sector median (requires sector_map)
      - None: no fill
    """
    if method is None:
        return df
    if method == "median":
        return df.apply(lambda row: row.fillna(row.median()), axis=1)
    if method == "sector_median":
        if sector_map is None:
            return df
        def _fill(row: pd.Series) -> pd.Series:
            aligned = row.reindex(sector_map.index)
            sectors = sector_map.loc[aligned.index]
            out = aligned.copy()
            for sector, tickers in sectors.groupby(sectors).groups.items():
                vals = aligned.loc[tickers]
                med = vals.median()
                out.loc[tickers] = vals.fillna(med)
            return out.reindex(row.index)
        return df.apply(_fill, axis=1)
    return df


def neutralize_factor(df: pd.DataFrame, method: str = "sector", sector_map: pd.Series | None = None) -> pd.DataFrame:
    """
    Demean by sector (default) or globally.
    method: 'sector' (requires sector_map) or 'global'
    """
    if method == "sector" and sector_map is not None:
        return sector_neutralize(df, sector_map)
    if method == "global":
        return df.apply(lambda row: row - row.mean(), axis=1)
    return df


def drop_all_nan(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna(how="all")


def clean_factor(
    raw_factor: pd.DataFrame,
    sector_map: pd.Series | None = None,
    winsor_limits: tuple[float, float] = (0.01, 0.99),
    min_coverage: float = 0.3,
    fill_method: str | None = "median",
    neutralize_method: str = "sector",
) -> pd.DataFrame:
    """
    Apply common cleanup steps:
      - drop dates with insufficient cross-sectional coverage
      - winsorize
      - optional fill
      - neutralize (sector/global)
      - z-score
      - drop all-NaN dates
    """
    if raw_factor.empty:
        return raw_factor

    df = raw_factor.copy()
    df = coverage_filter(df, min_coverage=min_coverage)
    df = winsorize(df, lower=winsor_limits[0], upper=winsor_limits[1])
    df = fill_factor(df, method=fill_method, sector_map=sector_map)
    df = neutralize_factor(df, method=neutralize_method, sector_map=sector_map)
    df = zscore(df)
    df = drop_all_nan(df)
    return df
