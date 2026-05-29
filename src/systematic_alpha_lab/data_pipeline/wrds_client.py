from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)


def fetch_sp500_constituents(
    start: date,
    end: date,
    username: str,
    password: str,
    library: str = "crsp_a_indexes",
    table: str = "dsp500list_v2",
    names_library: str = "crsp",
    names_table: str = "msenames",
) -> pd.DataFrame:
    """
    Pull S&P 500 constituents from WRDS and expand to daily rows.

    Returns DataFrame with columns: date, ticker, permno.
    """
    try:
        import wrds  # type: ignore
    except ImportError as exc:
        raise ImportError("wrds package is required for WRDS access") from exc

    db = wrds.Connection(wrds_username=username, wrds_password=password)
    # Inspect constituent table
    probe = db.raw_sql(f"select * from {library}.{table} limit 0")
    cols = set(probe.columns.str.lower())
    required = {"permno", "mbrstartdt", "mbrenddt"}
    if not required.issubset(cols):
        db.close()
        missing = required - cols
        raise RuntimeError(
            f"WRDS table {library}.{table} is missing columns {missing}. "
            "Provide tickers_override or point to a membership table with permno,mbrstartdt,mbrenddt."
        )

    # Fetch constituents and name history
    cons_query = f"select permno, mbrstartdt, mbrenddt from {library}.{table}"
    names_query = f"select permno, ticker, namedt, nameendt from {names_library}.{names_table}"
    logger.info("Querying WRDS for constituents: %s", cons_query)
    const_raw = db.raw_sql(cons_query)
    logger.info("Querying WRDS for permno->ticker mapping: %s", names_query)
    names_raw = db.raw_sql(names_query)
    db.close()

    const_raw["mbrstartdt"] = pd.to_datetime(const_raw["mbrstartdt"]).dt.date
    const_raw["mbrenddt"] = pd.to_datetime(const_raw["mbrenddt"]).dt.date
    const_raw["permno"] = const_raw["permno"].astype(int)

    names_raw["namedt"] = pd.to_datetime(names_raw["namedt"]).dt.date
    names_raw["nameendt"] = pd.to_datetime(names_raw["nameendt"]).dt.date
    names_raw["permno"] = names_raw["permno"].astype(int)
    names_raw["ticker"] = names_raw["ticker"].astype(str).str.strip()

    dates = pd.date_range(start=start, end=end, freq="D")
    daily = []
    for dt in dates:
        mask = (const_raw["mbrstartdt"] <= dt.date()) & (
            (const_raw["mbrenddt"].isna()) | (const_raw["mbrenddt"] >= dt.date())
        )
        active = const_raw.loc[mask, ["permno"]].copy()
        active["date"] = dt.date()
        daily.append(active)

    expanded = pd.concat(daily, ignore_index=True)
    # Map tickers by overlapping date ranges in names table
    merged = expanded.merge(names_raw, on="permno", how="left")
    merged = merged[
        (merged["namedt"].isna())  # keep rows without names for fallback
        | (
            (merged["namedt"] <= merged["date"])
            & ((merged["nameendt"].isna()) | (merged["nameendt"] >= merged["date"]))
        )
    ]

    merged["ticker"] = merged["ticker"].fillna(merged["permno"].astype(str))
    return merged[["date", "ticker", "permno"]]


def fetch_ff_factors(
    start: date,
    end: date,
    username: str,
    password: str,
    library: str = "ff_all",
    table: str = "factors_daily",
) -> pd.DataFrame:
    """
    Pull Fama-French factors (including market, SMB, HML, etc.) from WRDS.
    Returns columns: date, mktrf, smb, hml, rmw, cma, rf, umd (when available).
    """
    try:
        import wrds  # type: ignore
    except ImportError as exc:
        raise ImportError("wrds package is required for WRDS access") from exc

    db = wrds.Connection(wrds_username=username, wrds_password=password)
    ff_query = f"select * from {library}.{table}"
    logger.info("Querying WRDS for FF factors: %s", ff_query)
    ff = db.raw_sql(ff_query)

    db.close()
    ff.columns = [c.lower() for c in ff.columns]
    if "date" in ff.columns:
        ff["date"] = pd.to_datetime(ff["date"]).dt.date
        ff = ff[(ff["date"] >= start) & (ff["date"] <= end)]
    return ff
