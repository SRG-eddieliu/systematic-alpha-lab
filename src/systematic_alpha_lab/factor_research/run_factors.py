from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Type, Tuple, Dict, Any

import pandas as pd

from .analytics import (
    compute_all_analytics,
    compute_factor_correlation,
    save_correlation_matrix,
    corr_with_ff,
    update_registry,
    save_diagnostics,
)
from .data_loader import DataLoader
from .factor_definitions import get_default_factors
from .paths import factors_dir

logger = logging.getLogger(__name__)


def _run_factor_task(
    factor,
    sector_map,
    fwd_returns: pd.DataFrame,
    ff: pd.DataFrame | None,
) -> Tuple[str, pd.DataFrame, dict]:
    """
    Helper to compute a single factor and analytics.
    Uses a fresh DataLoader per task to avoid shared-state issues in threads.
    """
    loader = DataLoader()
    raw_scores = factor.compute(loader, sector_map=sector_map)
    analytics = compute_all_analytics(
        raw_scores,
        fwd_returns,
        factor_name=factor.name,
        write_registry=False,  # registry updated in caller to avoid contention
        ff_factors=ff,
    )
    return factor.name, raw_scores, analytics


def wide_to_long(df: pd.DataFrame, value_name: str = "Value") -> pd.DataFrame:
    out = df.stack().reset_index()
    out.columns = ["Date", "Ticker", value_name]
    out = out.dropna(subset=[value_name])
    out["Date"] = pd.to_datetime(out["Date"]).dt.date
    return out


def save_factor(factor_name: str, factor_df: pd.DataFrame) -> Path:
    factors_dir().mkdir(parents=True, exist_ok=True)
    path = factors_dir() / f"factor_{factor_name}.parquet"
    long_df = wide_to_long(factor_df)
    long_df.to_parquet(path, index=False)
    logger.info("Saved factor %s to %s", factor_name, path)
    return path


def save_ls_returns(name: str, ls: pd.Series) -> Path:
    factors_dir().mkdir(parents=True, exist_ok=True)
    path = factors_dir() / f"ls_{name}.parquet"
    df = ls.reset_index()
    df.columns = ["Date", "LS_Return"]
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    df.to_parquet(path, index=False)
    logger.info("Saved LS returns for %s to %s", name, path)
    return path


def compute_factors(parallel: bool = False, max_workers: int | None = None):
    """
    Step 1: compute factors (cleaned, shifted), forward returns, and LS PnL time series.
    Returns (factors dict, ls_returns dict, ff DataFrame).
    Persists factors and LS PnL to disk.
    """
    loader = DataLoader()
    sector_map = None
    try:
        sector_map = loader.load_sector_map()
    except Exception:
        logger.warning("Sector map unavailable; sector neutralization will be skipped.")

    ff = None
    try:
        ff = loader.load_ff_factors()
        ff_path = factors_dir() / "factor_ff_timeseries.parquet"
        ff_path.parent.mkdir(parents=True, exist_ok=True)
        ff.to_parquet(ff_path)
        logger.info("Saved FF factors to %s", ff_path)
    except Exception as exc:
        logger.warning("FF factors not available: %s", exc)

    price_wide = loader.load_price_wide(dataset="price_daily")
    fwd_returns = loader.forward_returns(price_wide)

    factors = get_default_factors()
    factor_outputs: Dict[str, pd.DataFrame] = {}
    ls_returns: Dict[str, pd.Series] = {}

    def _task(f):
        raw_scores = f.compute(loader, sector_map=sector_map)
        return f.name, raw_scores

    if parallel:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_task, factor): factor.name for factor in factors}
            for fut in as_completed(futures):
                name, raw_scores = fut.result()
                factor_outputs[name] = raw_scores
    else:
        for factor in factors:
            name, raw_scores = _task(factor)
            factor_outputs[name] = raw_scores

    # Persist factors and LS PnL
    for name, raw_scores in factor_outputs.items():
        save_factor(name, raw_scores)
        # Compute LS PnL for reuse in downstream steps
        analytics = compute_all_analytics(raw_scores, fwd_returns, factor_name=name, write_registry=False, ff_factors=ff)
        ls_series = analytics.get("ls_returns")
        if ls_series is not None:
            ls_returns[name] = ls_series
            save_ls_returns(name, ls_series)

    return factor_outputs, ls_returns, ff, fwd_returns


def run_analytics_only(
    factors: Dict[str, pd.DataFrame],
    fwd_returns: pd.DataFrame,
    ff: pd.DataFrame | None = None,
    write_registry: bool = True,
):
    """
    Step 2: compute analytics given precomputed factors and fwd returns.
    Returns analytics_results dict; optionally writes registry/diagnostics.
    """
    analytics_results: Dict[str, dict] = {}
    for name, raw_scores in factors.items():
        analytics = compute_all_analytics(
            raw_scores,
            fwd_returns,
            factor_name=name,
            write_registry=write_registry,
            ff_factors=ff,
        )
        analytics_results[name] = analytics
    return analytics_results


def compute_correlations_only(
    factors: Dict[str, pd.DataFrame],
    ls_returns: Dict[str, pd.Series] | None = None,
    ff: pd.DataFrame | None = None,
):
    """
    Step 3: factor cross-correlation and LS vs FF correlation.
    """
    corr = compute_factor_correlation(factors)
    corr_path = None
    if not corr.empty:
        corr_path = save_correlation_matrix(corr)
    ff_corr_path = None
    if ff is not None and ls_returns:
        ff_corr = corr_with_ff(ls_returns, ff)
        if not ff_corr.empty:
            ff_corr_path = save_correlation_matrix(
                ff_corr,
                path=factors_dir() / "factor_ff_correlation.parquet",
                ref_name="factor_ff_correlation",
            )
    return corr_path, ff_corr_path


def run_time_effects(
    factors: Dict[str, pd.DataFrame],
    fwd_returns: pd.DataFrame,
    window: int = 252,
    step: int = 21,
):
    """
    Step 4: rolling IC/IC IR to see time-varying performance.
    Returns a DataFrame with factor, date, rolling_mean_ic, rolling_ic_ir.
    """
    rows = []
    for name, fac in factors.items():
        ic = compute_all_analytics(fac, fwd_returns, write_registry=False, run_ls_ptf=False)["ic"]
        ic_roll = ic.rolling(window).mean()
        ic_std = ic.rolling(window).std(ddof=1)
        ic_ir = ic_roll / ic_std
        sampled = ic_roll.iloc[::step]
        for dt, val in sampled.dropna().items():
            rows.append({"factor": name, "date": dt, "rolling_mean_ic": val, "rolling_ic_ir": ic_ir.get(dt)})
    df = pd.DataFrame(rows)
    if not df.empty:
        out = factors_dir() / "factor_rolling_analytics.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)
        # Diagnostics copies (Parquet + CSV) for quick inspection
        diag_dir = Path(__file__).resolve().parents[1] / "diagnostics"
        diag_dir.mkdir(parents=True, exist_ok=True)
        diag_parquet = diag_dir / "factor_rolling_analytics.parquet"
        diag_csv = diag_dir / "factor_rolling_analytics.csv"
        df.to_parquet(diag_parquet, index=False)
        df.to_csv(diag_csv, index=False)
        logger.info("Saved rolling analytics to %s and diagnostics copies to %s/%s", out, diag_dir, diag_csv.name)
    return df


def run_all(parallel: bool = False, max_workers: int | None = None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    # Step 1: compute factors + LS PnL
    factor_outputs, ls_returns, ff, fwd_returns = compute_factors(parallel=parallel, max_workers=max_workers)
    # Step 2: analytics
    analytics_results = run_analytics_only(factor_outputs, fwd_returns, ff=ff, write_registry=True)
    # Step 3: correlations
    compute_correlations_only(factor_outputs, ls_returns=ls_returns, ff=ff)
    # Step 4: rolling time effects
    run_time_effects(factor_outputs, fwd_returns)


if __name__ == "__main__":
    run_all()
