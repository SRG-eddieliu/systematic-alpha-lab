from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import yaml

from .alpha_vantage_mcp import AlphaVantageMCPClient
from .alpha_vantage_rest import AlphaVantageRESTClient
from .config_loader import load_credentials
from .paths import raw_data_dir, repo_root
from .wrds_client import fetch_sp500_constituents

logger = logging.getLogger(__name__)

FULL_HISTORY_ENDPOINTS_DEFAULT = [
    "COMPANY_OVERVIEW",
    "INCOME_STATEMENT",
    "BALANCE_SHEET",
    "CASH_FLOW",
    "EARNINGS",
    "EARNINGS_ESTIMATES",
    "DIVIDENDS",
    "SPLITS",
    "SYMBOL_SEARCH",
]

TIME_SERIES_ENDPOINTS_DEFAULT = [
    "TIME_SERIES_DAILY_ADJUSTED",
    "TIME_SERIES_WEEKLY_ADJUSTED",
]

ECONOMIC_ENDPOINTS_DEFAULT = [
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
]

REST_FUNCTION_MAP: Dict[str, str] = {
    "COMPANY_OVERVIEW": "OVERVIEW",
    "INCOME_STATEMENT": "INCOME_STATEMENT",
    "BALANCE_SHEET": "BALANCE_SHEET",
    "CASH_FLOW": "CASH_FLOW",
    "EARNINGS": "EARNINGS",
    "EARNINGS_ESTIMATES": "EARNINGS_ESTIMATES",
    "DIVIDENDS": "DIVIDENDS",
    "SPLITS": "SPLITS",
    "SYMBOL_SEARCH": "SYMBOL_SEARCH",
}


def _content_to_df(content: Any) -> pd.DataFrame:
    """Normalize MCP content payload into a tidy DataFrame."""
    import ast
    from io import StringIO

    def _maybe_reparse_text_df(df: pd.DataFrame) -> pd.DataFrame:
        # If we only have a single text column, attempt one more literal_eval pass.
        if list(df.columns) == ["text"] and len(df) == 1:
            txt = df.iloc[0, 0]
            try:
                parsed = ast.literal_eval(txt)
                return _content_to_df(parsed)
            except Exception:
                return df
        return df

    def _strip_prefix(col: str) -> str:
        if ". " in col:
            prefix, rest = col.split(". ", 1)
            if prefix.replace(".", "").isdigit():
                return rest
        return col

    def _parse_time_series(payload: Dict[str, Any], meta: Dict[str, Any]) -> pd.DataFrame:
        records = []
        symbol = meta.get("2. Symbol") or meta.get("1. Symbol")
        for dt_str, vals in payload.items():
            rec: Dict[str, Any] = {"date": pd.to_datetime(dt_str).date()}
            for k, v in vals.items():
                rec[_strip_prefix(k)] = pd.to_numeric(v, errors="ignore")
            if symbol:
                rec["symbol"] = symbol
            records.append(rec)
        return pd.DataFrame(records)

    def _parse_global_quote(payload: Dict[str, Any]) -> pd.DataFrame:
        rec = {_strip_prefix(k): v for k, v in payload.items()}
        if "symbol" not in rec and "01. symbol" in payload:
            rec["symbol"] = payload.get("01. symbol")
        return pd.DataFrame([rec])

    def _try_parse_text(text: str) -> pd.DataFrame:
        # Try JSON
        try:
            parsed = json.loads(text)
            return _content_to_df(parsed)
        except json.JSONDecodeError:
            pass
        # Try Python literal (since MCP text uses single quotes)
        try:
            parsed = ast.literal_eval(text)
            return _content_to_df(parsed)
        except Exception:
            pass
        # Then try CSV
        try:
            return pd.read_csv(StringIO(text))
        except Exception:
            return pd.DataFrame({"text": [text]})

    # Handle typical MCP "content" wrappers
    if isinstance(content, list):
        if content and isinstance(content[0], dict) and "text" in content[0]:
            # Parse the single text payload into a dict and handle time series
            txt = content[0].get("text", "")
            try:
                payload = ast.literal_eval(txt)
                return _content_to_df(payload)
            except Exception:
                frames = [_try_parse_text(txt)]
                frames = [f for f in frames if not f.empty]
                if frames:
                    return _maybe_reparse_text_df(pd.concat(frames, ignore_index=True))
                return _maybe_reparse_text_df(pd.DataFrame({"text": [txt]}))
        return pd.json_normalize(content)

    if isinstance(content, dict):
        # Handle preview wrapper with CSV sample_data
        if content.get("preview") and content.get("data_type") == "csv" and "sample_data" in content:
            csv_text = content["sample_data"]
            try:
                df = pd.read_csv(StringIO(csv_text))
                # Attach symbol if available
                if "symbol" in content:
                    df["symbol"] = content["symbol"]
                return df
            except Exception:
                return pd.DataFrame({"text": [csv_text]})
        # Time series keys
        ts_key = next((k for k in content.keys() if "Time Series" in k), None)
        ta_key = next((k for k in content.keys() if "Technical Analysis" in k), None)
        if ts_key:
            return _parse_time_series(content[ts_key], content.get("Meta Data", {}))
        if ta_key:
            return _parse_time_series(content[ta_key], content.get("Meta Data", {}))
        if "Global Quote" in content:
            return _parse_global_quote(content["Global Quote"])
        return pd.json_normalize(content)

    if isinstance(content, str):
        return _try_parse_text(content)

    return pd.DataFrame({"value": [content]})


def _write_parquet(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    logger.info("Wrote %d rows to %s", len(df), path)


def _all_period_files_exist(base_dir: Path, endpoint: str, ticker: str) -> bool:
    annual_path = base_dir / endpoint / "annual" / f"{ticker}.parquet"
    quarterly_path = base_dir / endpoint / "quarterly" / f"{ticker}.parquet"
    if not (annual_path.exists() and quarterly_path.exists()):
        return False
    try:
        a = pd.read_parquet(annual_path)
        q = pd.read_parquet(quarterly_path)
        return not a.empty and not q.empty
    except Exception:
        return False


def _write_split_by_period(df: pd.DataFrame, base_dir: Path, endpoint: str, ticker: str) -> None:
    if "period_type" not in df.columns:
        _write_parquet(df, base_dir / endpoint / f"{ticker}.parquet")
        return
    for period in ["annual", "quarterly"]:
        sub = df[df["period_type"] == period].drop(columns=["period_type"], errors="ignore")
        if sub.empty:
            continue
        _write_parquet(sub, base_dir / endpoint / period / f"{ticker}.parquet")


def _filter_date(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    for col in ["date", "timestamp", "datetime"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).dt.date
            filtered = df[(df[col] >= start) & (df[col] <= end)]
            # If nothing falls in range (e.g., API returns future dates), keep original to avoid dropping everything.
            return filtered if not filtered.empty else df
    return df


def _json_to_df(payload: Dict[str, Any]) -> pd.DataFrame:
    """Flatten Alpha Vantage JSON responses into a DataFrame."""
    # Handle paired annual/quarterly collections explicitly.
    if "annualReports" in payload or "quarterlyReports" in payload:
        frames = []
        if payload.get("annualReports"):
            df_a = pd.json_normalize(payload["annualReports"])
            df_a["period_type"] = "annual"
            frames.append(df_a)
        if payload.get("quarterlyReports"):
            df_q = pd.json_normalize(payload["quarterlyReports"])
            df_q["period_type"] = "quarterly"
            frames.append(df_q)
        if frames:
            return pd.concat(frames, ignore_index=True)

    if "annualEarnings" in payload or "quarterlyEarnings" in payload:
        frames = []
        if payload.get("annualEarnings"):
            df_a = pd.json_normalize(payload["annualEarnings"])
            df_a["period_type"] = "annual"
            frames.append(df_a)
        if payload.get("quarterlyEarnings"):
            df_q = pd.json_normalize(payload["quarterlyEarnings"])
            df_q["period_type"] = "quarterly"
            frames.append(df_q)
        if frames:
            return pd.concat(frames, ignore_index=True)

    if "annualEarningsEstimates" in payload or "quarterlyEarningsEstimates" in payload:
        frames = []
        if payload.get("annualEarningsEstimates"):
            df_a = pd.json_normalize(payload["annualEarningsEstimates"])
            df_a["period_type"] = "annual"
            frames.append(df_a)
        if payload.get("quarterlyEarningsEstimates"):
            df_q = pd.json_normalize(payload["quarterlyEarningsEstimates"])
            df_q["period_type"] = "quarterly"
            frames.append(df_q)
        if frames:
            return pd.concat(frames, ignore_index=True)

    # Common list fields
    for key in ["annualReports", "quarterlyReports", "bestMatches", "data"]:
        if key in payload and isinstance(payload[key], list):
            return pd.json_normalize(payload[key])
    # Fallback: first list value
    for v in payload.values():
        if isinstance(v, list):
            return pd.json_normalize(v)
    return pd.json_normalize(payload)


def _get_wrds_creds(creds: Dict[str, Any]) -> Dict[str, str]:
    if "wrds" in creds:
        return creds["wrds"]
    return {
        "username": creds.get("wrds_username") or creds.get("username"),
        "password": creds.get("wrds_password") or creds.get("password"),
    }


def run_ingestion(
    date_start: Optional[date] = None,
    date_end: Optional[date] = None,
    sleep_seconds: float = 12.0,
    use_paid_key: bool = True,
    tickers_override: Optional[List[str]] = None,
    resume: bool = True,
    fetch_ff: bool = True,
) -> None:
    """
    Ingest WRDS constituents and Alpha Vantage data into raw Parquet files.
    """
    creds = load_credentials()
    av_key = creds.get("alphavantage_api_paid" if use_paid_key else "alphavantage_api")
    if not av_key:
        raise ValueError("Alpha Vantage API key missing in credentials.yml")

    # Load default dates and endpoints from config if not provided
    cfg_path = repo_root() / "config" / "datalist.yml"
    av_cfg: Dict[str, Any] = {}
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            av_cfg = cfg.get("alpha_vantage", {})
            defaults = cfg.get("defaults", {})
            ds = defaults.get("start_date")
            de = defaults.get("end_date")
            if date_start is None and ds:
                date_start = date.fromisoformat(ds)
            if date_end is None and de:
                date_end = date.fromisoformat(de)
        except Exception as exc:
            logger.warning("Failed to read config dates: %s", exc)
    else:
        av_cfg = {}

    if date_start is None or date_end is None:
        raise ValueError("date_start and date_end must be provided or defined in config/datalist.yml defaults.")

    time_series_endpoints = av_cfg.get("time_series", TIME_SERIES_ENDPOINTS_DEFAULT)
    full_history_endpoints = av_cfg.get("fundamentals", FULL_HISTORY_ENDPOINTS_DEFAULT)
    economic_endpoints = av_cfg.get("economic_indicators", ECONOMIC_ENDPOINTS_DEFAULT)
    # Future expansion is currently unused but can be added here if needed.

    # Try to pull MCP base_url from .vscode/mcp.json (server 'alphavantage'); fall back to default.
    mcp_base_url = "https://mcp.alphavantage.co/mcp"
    mcp_cfg_path = repo_root() / ".vscode" / "mcp.json"
    if mcp_cfg_path.exists():
        try:
            cfg = json.loads(mcp_cfg_path.read_text())
            srv = cfg.get("servers", {}).get("alphavantage", {})
            url = srv.get("url")
            if url:
                mcp_base_url = url
                logger.info("Using MCP server URL from %s: %s", mcp_cfg_path, mcp_base_url)
        except Exception as exc:
            logger.warning("Failed to read %s: %s. Using default MCP URL.", mcp_cfg_path, exc)

    wrds_creds = _get_wrds_creds(creds)
    if not wrds_creds.get("username") or not wrds_creds.get("password"):
        raise ValueError("WRDS credentials missing in credentials.yml")

    client = AlphaVantageMCPClient(api_key=av_key, base_url=mcp_base_url)
    rest_client = AlphaVantageRESTClient(api_key=av_key)

    if tickers_override:
        tickers = sorted(set(tickers_override))
        logger.info("Using provided tickers override (%d tickers); skipping WRDS.", len(tickers))
        dates = pd.date_range(start=date_start, end=date_end, freq="D")
        constituents = pd.DataFrame(
            [(d.date(), t) for d in dates for t in tickers],
            columns=["date", "ticker"],
        )
        constituents["permno"] = constituents["ticker"]
    else:
        logger.info("Fetching S&P 500 constituents from WRDS")
        try:
            constituents = fetch_sp500_constituents(
                start=date_start,
                end=date_end,
                username=wrds_creds["username"],
                password=wrds_creds["password"],
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc} | Provide tickers_override to run_ingestion if your WRDS instance lacks membership columns."
            ) from exc
        logger.info("Expanded constituents to %d daily rows", len(constituents))

    raw_dir = raw_data_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)
    if fetch_ff:
        try:
            ff_df = fetch_ff_factors(date_start, date_end, wrds_creds["username"], wrds_creds["password"])
            ff_path = final_dir() / "FAMA_FRENCH_FACTORS.parquet"
            ff_path.parent.mkdir(parents=True, exist_ok=True)
            ff_df.to_parquet(ff_path, index=False)
            logger.info("Wrote %d rows to %s", len(ff_df), ff_path)
        except Exception as exc:
            logger.warning("Failed to fetch Fama-French factors: %s", exc)

    # Drop rows without tickers (avoid <NA> values downstream)
    constituents = constituents[constituents["ticker"].notna()].copy()
    # Remove string artifacts like "<NA>" / "nan" / empty
    constituents["ticker"] = constituents["ticker"].astype(str).str.strip()
    bad_tokens = {"<na>", "nan", "none", ""}
    constituents = constituents[~constituents["ticker"].str.lower().isin(bad_tokens)]

    # WRDS output
    _write_parquet(constituents, raw_dir / "wrds_sp500_constituents.parquet")

    # Unique ticker list to drive API calls (dates not needed for Alpha Vantage loops)
    tickers = sorted(constituents["ticker"].unique())
    _write_parquet(pd.DataFrame({"ticker": tickers}), raw_dir / "wrds_sp500_unique_tickers.parquet")

    # Full history endpoints: call once per ticker when applicable.
    for ticker in tickers:
        for endpoint in time_series_endpoints:
            # Use direct REST call for full CSV without preview truncation.
            function = endpoint
            out_path = raw_dir / endpoint / f"{ticker}.parquet"
            if resume and out_path.exists():
                try:
                    existing = pd.read_parquet(out_path)
                    if not existing.empty:
                        logger.info("Skipping %s %s (resume enabled, file already exists)", endpoint, ticker)
                        continue
                except Exception:
                    pass
            df = rest_client.fetch_time_series_csv(function=function, symbol=ticker, outputsize="full")
            df = _filter_date(df, date_start, date_end)
            _write_parquet(df, out_path)
            time.sleep(sleep_seconds)

        for endpoint in full_history_endpoints:
            params: Dict[str, Any] = {}
            function = REST_FUNCTION_MAP.get(endpoint, endpoint)
            out_path = raw_dir / endpoint / f"{ticker}.parquet"
            periodized = endpoint in {
                "INCOME_STATEMENT",
                "BALANCE_SHEET",
                "CASH_FLOW",
                "EARNINGS",
                "EARNINGS_ESTIMATES",
            }
            if resume:
                if periodized and _all_period_files_exist(raw_dir, endpoint, ticker):
                    logger.info("Skipping %s %s (resume enabled, annual+quarterly exist)", endpoint, ticker)
                    continue
                if (not periodized) and out_path.exists():
                    try:
                        existing = pd.read_parquet(out_path)
                        if not existing.empty:
                            logger.info("Skipping %s %s (resume enabled, file already exists)", endpoint, ticker)
                            continue
                    except Exception:
                        pass
            if endpoint in {
                "COMPANY_OVERVIEW",
                "INCOME_STATEMENT",
                "BALANCE_SHEET",
                "CASH_FLOW",
                "EARNINGS",
                "EARNINGS_ESTIMATES",
                "DIVIDENDS",
                "SPLITS",
                "ETF_PROFILE",
            }:
                params["symbol"] = ticker
            elif endpoint == "SYMBOL_SEARCH":
                params["keywords"] = ticker
            # LISTING_STATUS, EARNINGS_CALENDAR, IPO_CALENDAR need no symbol.

            payload = rest_client.fetch_json(function=function, params=params)
            df = _filter_date(_json_to_df(payload), date_start, date_end)
            _write_split_by_period(df, raw_dir, endpoint, ticker)
            time.sleep(sleep_seconds)


    # Economic indicators: single calls without ticker.
    for endpoint in economic_endpoints:
        function = REST_FUNCTION_MAP.get(endpoint, endpoint)
        out_path = raw_dir / endpoint / "global.parquet"
        if resume and out_path.exists():
            try:
                existing = pd.read_parquet(out_path)
                if not existing.empty:
                    logger.info("Skipping %s (resume enabled, file already exists)", endpoint)
                    continue
            except Exception:
                pass
        payload = rest_client.fetch_json(function=function, params={})
        df = _filter_date(_json_to_df(payload), date_start, date_end)
        _write_parquet(df, out_path)
        time.sleep(sleep_seconds)
