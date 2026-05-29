from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .alpha_vantage_rest import AlphaVantageRESTClient
from .config_loader import load_credentials
from .ingestion import REST_FUNCTION_MAP, _json_to_df, _write_split_by_period
from .paths import final_dataset_path, final_dir, raw_data_dir

logger = logging.getLogger(__name__)


def export_fundamental_failures(temp_csv: Optional[Path] = None) -> Path:
    """
    Scan the fundamentals dataset for rows containing 'invalid api call'
    and write a CSV with the affected ticker/statement and suggested REST URLs.
    """
    df = pd.read_parquet(final_dataset_path("fundamentals"))
    mask = df.astype(str).apply(lambda col: col.str.contains("invalid api call", case=False, na=False)).any(axis=1)
    failures = df.loc[mask].copy()
    if failures.empty:
        logger.info("No 'invalid api call' rows found in fundamentals dataset.")
        return temp_csv or final_dir() / "failures_temp.csv"

    # Derive basic metadata
    cols = [c for c in failures.columns if c in {"ticker", "statement", "symbol"}]
    out = failures[cols].copy() if cols else pd.DataFrame(index=failures.index)
    if "ticker" not in out.columns and "symbol" in failures.columns:
        out["ticker"] = failures["symbol"]
    if "statement" not in out.columns and "function" in failures.columns:
        out["statement"] = failures["function"]

    # Suggested API call
    out["function"] = out.get("statement", None) if "statement" in out else out.get("function", None)
    out["api_url"] = out.apply(
        lambda r: f"https://www.alphavantage.co/query?function={r.get('function')}&symbol={r.get('ticker')}&apikey=YOUR_KEY",
        axis=1,
    )

    target = temp_csv or final_dir() / "failures_temp.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(target, index=False)
    logger.info("Exported %d fundamental failures to %s", len(out), target)
    return target


def export_company_overview_failures(temp_csv: Optional[Path] = None) -> Path:
    """
    Scan the company_overview dataset for rows containing 'invalid api call'
    and write a CSV with ticker and suggested REST URLs to re-fetch.
    """
    df = pd.read_parquet(final_dataset_path("company_overview"))
    mask = df.astype(str).apply(lambda col: col.str.contains("invalid api call", case=False, na=False)).any(axis=1)
    failures = df.loc[mask].copy()
    if failures.empty:
        logger.info("No 'invalid api call' rows found in company_overview dataset.")
        return temp_csv or final_dir() / "company_overview_failures.csv"

    out = pd.DataFrame()
    if "ticker" in failures.columns:
        out["ticker"] = failures["ticker"]
    elif "symbol" in failures.columns:
        out["ticker"] = failures["symbol"]
    else:
        out["ticker"] = ""

    out["function"] = "OVERVIEW"
    out["api_url"] = out.apply(
        lambda r: f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={r.get('ticker')}&apikey=YOUR_KEY",
        axis=1,
    )

    target = temp_csv or final_dir() / "company_overview_failures.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(target, index=False)
    logger.info("Exported %d company overview failures to %s", len(out), target)
    return target


def export_all_failures(temp_csv: Optional[Path] = None) -> Path:
    """
    Scan all raw parquet files for 'invalid api call' content and write a CSV with
    ticker, function (endpoint), and suggested REST URL.
    """
    logger.info("Scanning raw data for failures...")
    rows = []
    base = raw_data_dir()
    for path in base.rglob("*.parquet"):
        if path.name.startswith("wrds_"):
            continue
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if df.empty:
            continue
        if not df.astype(str).apply(
            lambda c: c.str.contains("invalid api call|thank you for using alpha vantage", case=False, na=False)
        ).any().any():
            continue
        parent = path.parent.name
        endpoint = parent
        if parent in {"annual", "quarterly"}:
            endpoint = path.parent.parent.name
        ticker = path.stem
        rows.append(
            {
                "ticker": ticker,
                "function": endpoint,
                "path": str(path),
                "api_url": f"https://www.alphavantage.co/query?function={REST_FUNCTION_MAP.get(endpoint, endpoint)}&symbol={ticker}&apikey=YOUR_KEY",
                "error_sample": df.astype(str).stack().iloc[0],
            }
        )
    if not rows:
        logger.info("No failures found in raw data.")
        return temp_csv or final_dir() / "failures_all.csv"

    out_df = pd.DataFrame(rows)
    target = temp_csv or final_dir() / "failures_all.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(target, index=False)
    logger.info("Exported %d failures to %s", len(out_df), target)
    return target


def refetch_failures(failures_csv: Path, use_paid_key: bool = True, sleep_seconds: float = 1.0) -> None:
    """
    Re-fetch failed fundamentals/company overview calls listed in the given CSV
    and overwrite the raw parquet files. CSV expected columns: ticker, function.
    """
    failures = pd.read_csv(failures_csv)
    if failures.empty:
        logger.info("No failures to refetch in %s", failures_csv)
        return

    creds = load_credentials()
    api_key = creds.get("alphavantage_api_paid" if use_paid_key else "alphavantage_api")
    if not api_key:
        raise ValueError("Alpha Vantage API key missing in credentials.yml")

    rest_client = AlphaVantageRESTClient(api_key=api_key)
    base_dir = raw_data_dir()
    periodized = {"INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS", "EARNINGS_ESTIMATES"}

    logger.info("Refetching %d failures from %s", len(failures), failures_csv)
    for idx, (_, row) in enumerate(failures.iterrows(), start=1):
        ticker = row.get("ticker") or row.get("symbol")
        endpoint = row.get("function")
        if not ticker or not endpoint:
            continue
        function = REST_FUNCTION_MAP.get(endpoint, endpoint)
        logger.info("[%d/%d] Re-fetching %s for %s", idx, len(failures), function, ticker)
        try:
            payload = rest_client.fetch_json(function=function, params={"symbol": ticker})
            df = _json_to_df(payload)
            if endpoint in periodized:
                _write_split_by_period(df, base_dir, endpoint, ticker)
                # Drop stale single-file responses (often the original invalid payload).
                single_path = base_dir / endpoint / f"{ticker}.parquet"
                if single_path.exists():
                    single_path.unlink()
                    logger.info("Removed stale %s", single_path)
            else:
                out_path = base_dir / endpoint / f"{ticker}.parquet"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(out_path, index=False)
                logger.info("Wrote %d rows to %s", len(df), out_path)
        except Exception as exc:
            logger.error("Failed to refetch %s for %s: %s", function, ticker, exc)
        if sleep_seconds and sleep_seconds > 0:
            import time

            time.sleep(sleep_seconds)


def clean_final_invalid_calls(dataset: str = "all") -> dict[str, int]:
    """
    Remove rows containing 'invalid api call' from final parquet datasets.
    Returns a mapping of dataset name -> rows removed.
    """
    base = final_dir()
    datasets = sorted([p.stem for p in base.glob("*.parquet")]) if dataset == "all" else [dataset]
    removed: dict[str, int] = {}
    for name in datasets:
        path = final_dataset_path(name)
        if not path.exists():
            logger.warning("Final dataset not found: %s", path)
            continue
        df = pd.read_parquet(path)
        mask = df.astype(str).apply(lambda c: c.str.contains("invalid api call", case=False, na=False)).any(axis=1)
        count = int(mask.sum())
        if count == 0:
            continue
        df = df.loc[~mask].reset_index(drop=True)
        df.to_parquet(path, index=False)
        removed[name] = count
        logger.info("Removed %d invalid-api-call rows from %s", count, path)
    if not removed:
        logger.info("No invalid-api-call rows found in final datasets.")
    return removed
