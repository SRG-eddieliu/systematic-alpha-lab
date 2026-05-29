from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
from pandas.tseries.offsets import BusinessDay

from .paths import data_root, final_dataset_path, final_dir, raw_data_dir

logger = logging.getLogger(__name__)


def _infer_date_column(df: pd.DataFrame) -> Optional[str]:
    for col in ["date", "Date", "timestamp", "datetime"]:
        if col in df.columns:
            return col
    return None


_PRICE_FIELDS = {
    "1. open": "open",
    "2. high": "high",
    "3. low": "low",
    "4. close": "close",
    "5. adjusted close": "adjusted_close",
    "6. volume": "volume",
    "7. dividend amount": "dividend_amount",
    "8. split coefficient": "split_coefficient",
}
_PRICE_COLS = ["date", "open", "high", "low", "close", "adjusted_close", "volume", "dividend_amount", "split_coefficient"]
_WIDE_PREFIXES = (
    "Time Series (Daily)",
    "Weekly Adjusted Time Series",
)


def _unpivot_alpha_vantage_timeseries(df: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """Handle wide Alpha Vantage responses that arrive flattened with meta-data columns."""
    if df.empty:
        return None
    cols = [str(c) for c in df.columns]
    prefix = next((p for p in _WIDE_PREFIXES if any(c.startswith(p + ".") for c in cols)), None)
    if not prefix:
        return None

    pattern = re.compile(rf"^{re.escape(prefix)}\.(\d{{4}}-\d{{2}}-\d{{2}})\.(\d+)\.\s(.+)$")
    row = df.iloc[0]
    grouped: Dict[str, Dict[str, object]] = {}
    for col in cols:
        match = pattern.match(col)
        if not match:
            continue
        date_str, num, label = match.groups()
        field = _PRICE_FIELDS.get(f"{num}. {label}".strip())
        if not field:
            continue
        grouped.setdefault(date_str, {})[field] = row[col]

    if not grouped:
        return None

    records = []
    for date_str, values in grouped.items():
        values["date"] = date_str
        values["ticker"] = ticker
        records.append(values)

    return pd.DataFrame.from_records(records)


def _normalize_price(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    wide_df = _unpivot_alpha_vantage_timeseries(df, ticker)
    if wide_df is not None:
        df = wide_df
    else:
        df = df.copy()
        date_col = _infer_date_column(df)
        if date_col:
            df = df.rename(columns={date_col: "date"})
        if "date" not in df.columns:
            # Try to coerce first column to date if it looks like one; else set NaT
            first_col = df.columns[0]
            df = df.rename(columns={first_col: "date"})

    # Normalize column names and keep only expected price fields plus ticker.
    df = df.rename(
        columns={
            "adjusted close": "adjusted_close",
            "dividend amount": "dividend_amount",
            "split coefficient": "split_coefficient",
        }
    )
    df["ticker"] = ticker
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="ISO8601").dt.date
    for col in ("open", "high", "low", "close", "adjusted_close", "volume", "dividend_amount", "split_coefficient"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = [col for col in _PRICE_COLS + ["ticker"] if col in df.columns]
    return df[keep]


def _write(df: pd.DataFrame, name: str) -> Path:
    path = final_dataset_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    logger.info("Wrote %d rows to %s", len(df), path)
    return path


def transform_raw_to_final() -> Dict[str, Path]:
    """
    Build domain-specific final tables:
      - price_daily: from TIME_SERIES_DAILY_ADJUSTED
      - price_weekly: from TIME_SERIES_WEEKLY_ADJUSTED
      - fundamentals: all fundamentals endpoints, preserving period_type when present
      - economic_indicators: all economic indicator endpoints
      - company_overview: single-row metadata per ticker (from COMPANY_OVERVIEW)
    """
    raw_dir = raw_data_dir()
    paths = list(raw_dir.rglob("*.parquet"))
    if not paths:
        raise FileNotFoundError(f"No parquet files found under {raw_dir}")

    price_daily, price_weekly = [], []
    fundamentals_map: Dict[str, list[pd.DataFrame]] = {}
    econ = []
    company_overview = []
    failures = []

    fundamentals_endpoints = {
        "INCOME_STATEMENT",
        "BALANCE_SHEET",
        "CASH_FLOW",
        "EARNINGS",
        "EARNINGS_ESTIMATES",
        "DIVIDENDS",
        "SPLITS",
    }
    econ_endpoints = {
        "REAL_GDP",
        "REAL_GDP_PER_CAPITA",
        "TREASURY_YIELD",
        "FEDERAL_FUNDS_RATE",
        "CPI",
        "INFLATION",
        "RETAIL_SALES",
        "DURABLES",
        "UNEMPLOYMENT",
        "NONFARM_PAYROLL",
    }

    total = len(paths)
    logger.info("Transforming %d raw files from %s", total, raw_dir)

    for idx, path in enumerate(paths, start=1):
        if path.name.startswith("wrds_"):
            continue
        parent = path.parent.name
        grandparent = path.parent.parent.name if path.parent.parent else ""
        endpoint = grandparent if parent in {"annual", "quarterly"} else parent
        ticker = path.stem
        df = pd.read_parquet(path)
        if df.empty:
            continue

        if idx % 50 == 0 or idx == total:
            logger.info("Processed %d/%d files...", idx, total)

        # Detect API error/rate-limit payloads and log as failures, then skip.
        df_str = df.astype(str)
        err_mask = df_str.apply(
            lambda c: c.str.contains("invalid api call|thank you for using alpha vantage", case=False, na=False)
        ).any(axis=1)
        only_info_cols = set(df.columns) <= {"Information", "Error Message", "Note"}
        if err_mask.any() or only_info_cols:
            endpoint = parent if parent not in {"annual", "quarterly"} else path.parent.parent.name
            failures.append(
                {
                    "ticker": ticker,
                    "function": endpoint,
                    "path": str(path),
                    "error_sample": df_str.stack().iloc[0] if not df_str.empty else "",
                }
            )
            continue

        if endpoint == "TIME_SERIES_DAILY_ADJUSTED":
            price_daily.append(_normalize_price(df, ticker))
            continue
        if endpoint == "TIME_SERIES_WEEKLY_ADJUSTED":
            price_weekly.append(_normalize_price(df, ticker))
            continue

        if endpoint in fundamentals_endpoints:
            period_type = None
            if parent in ("annual", "quarterly"):
                period_type = parent
            elif grandparent in ("annual", "quarterly"):
                period_type = grandparent
            df = df.copy()
            df["ticker"] = ticker
            statement = endpoint
            df["statement"] = statement
            if period_type:
                df["period_type"] = period_type
            fundamentals_map.setdefault(statement, []).append(df)
            continue

        if endpoint in econ_endpoints:
            df = df.copy()
            df["indicator"] = endpoint
            econ.append(df)
            continue

        if endpoint == "COMPANY_OVERVIEW":
            df = df.copy()
            df["ticker"] = ticker
            company_overview.append(df)
            continue

    outputs: Dict[str, Path] = {}
    final_dir().mkdir(parents=True, exist_ok=True)

    if price_daily:
        daily_df = pd.concat(price_daily, ignore_index=True)
        daily_df = daily_df.dropna(subset=["date"])
        outputs["price_daily"] = _write(daily_df, "price_daily")
    else:
        logger.info("No price_daily data assembled.")
    if price_weekly:
        weekly_df = pd.concat(price_weekly, ignore_index=True)
        weekly_df = weekly_df.dropna(subset=["date"])
        outputs["price_weekly"] = _write(weekly_df, "price_weekly")
    else:
        logger.info("No price_weekly data assembled.")
    for statement, parts in fundamentals_map.items():
        stmt_df = pd.concat(parts, ignore_index=True)
        if "Information" in stmt_df.columns:
            stmt_df = stmt_df.drop(columns=["Information"])
        base_name = f"fundamentals_{statement.lower()}"

        outputs[base_name] = _write(stmt_df, base_name)
        if "period_type" in stmt_df.columns:
            for period in ["quarterly", "annual"]:
                sub = stmt_df[stmt_df["period_type"] == period].copy()
                if sub.empty:
                    continue
                outputs[f"{base_name}_{period}"] = _write(sub, f"{base_name}_{period}")
    if not fundamentals_map:
        logger.info("No fundamentals data assembled.")
    if econ:
        outputs["economic_indicators"] = _write(pd.concat(econ, ignore_index=True), "economic_indicators")
    else:
        logger.info("No economic indicator data assembled.")
    if company_overview:
        co_df = pd.concat(company_overview, ignore_index=True)
        # Drop noise columns that only hold error text/nulls (e.g., "Error Message") or are entirely empty.
        drop_cols = [c for c in co_df.columns if c == "Error Message" or co_df[c].notna().sum() == 0]
        if drop_cols:
            co_df = co_df.drop(columns=drop_cols)
        outputs["company_overview"] = _write(co_df, "company_overview")
    else:
        logger.info("No company_overview data assembled.")

    if not outputs:
        raise ValueError("No data to transform.")

    if failures:
        fail_path = final_dir() / "failures_all.csv"
        fail_df = pd.DataFrame(failures)
        fail_path.parent.mkdir(parents=True, exist_ok=True)
        if fail_path.exists():
            existing = pd.read_csv(fail_path)
            fail_df = pd.concat([existing, fail_df], ignore_index=True)
        fail_df.to_csv(fail_path, index=False)
        logger.warning("Logged %d failures with API error/rate-limit payloads to %s", len(failures), fail_path)

    return outputs
