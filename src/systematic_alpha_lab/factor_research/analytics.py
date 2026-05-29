from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

from .paths import factors_dir, repo_root

logger = logging.getLogger(__name__)


def _data_quality_stats(df: pd.DataFrame) -> Dict[str, float]:
    """
    Basic coverage diagnostics for a factor/composite panel.
    """
    if df is None or df.empty:
        return {
            "dq_total_dates": 0,
            "dq_total_tickers": 0,
            "dq_non_null_obs": 0,
            "dq_pct_non_null": np.nan,
            "dq_mean_coverage": np.nan,
            "dq_median_coverage": np.nan,
            "dq_min_coverage": np.nan,
            "dq_pct_allnan_dates": np.nan,
        }
    # Drop permanently empty rows/cols to avoid penalizing all-NaN tickers/dates
    df_use = df.loc[df.notna().any(axis=1), df.notna().any(axis=0)]
    total_dates = df_use.index.nunique()
    total_tickers = df_use.columns.nunique()
    total_cells = total_dates * total_tickers
    non_null = int(df_use.notna().sum().sum())
    pct_non_null = non_null / total_cells if total_cells else np.nan
    coverage = df_use.notna().mean(axis=1) if total_tickers else pd.Series(dtype=float)
    all_nan_dates = df_use.isna().all(axis=1)
    return {
        "dq_total_dates": total_dates,
        "dq_total_tickers": total_tickers,
        "dq_non_null_obs": non_null,
        "dq_pct_non_null": pct_non_null,
        "dq_mean_coverage": coverage.mean() if not coverage.empty else np.nan,
        "dq_median_coverage": coverage.median() if not coverage.empty else np.nan,
        "dq_min_coverage": coverage.min() if not coverage.empty else np.nan,
        "dq_pct_allnan_dates": all_nan_dates.mean() if len(all_nan_dates) else np.nan,
    }


def _spearman(x: pd.Series, y: pd.Series) -> float:
    if x.dropna().empty or y.dropna().empty:
        return np.nan
    aligned = pd.concat([x, y], axis=1, join="inner").dropna()
    if aligned.empty:
        return np.nan
    return aligned.corr(method="spearman").iloc[0, 1]


def information_coefficient(factor: pd.DataFrame, fwd_returns: pd.DataFrame) -> pd.Series:
    common_dates = factor.index.intersection(fwd_returns.index)
    ic = []
    for dt in common_dates:
        ic.append(_spearman(factor.loc[dt], fwd_returns.loc[dt]))
    return pd.Series(ic, index=common_dates).dropna()


def factor_autocorrelation(factor: pd.DataFrame) -> pd.Series:
    """
    Computes the lag-1 autocorrelation of the factor across time.
    Measuring how stable the factor rankings are over time.
    Lower values indicate more turnover in rankings and higher values indicate more stability.
    """
    dates = factor.index
    ac = []
    ac_dates = []
    for t, dt in enumerate(dates[:-1]):
        nxt = dates[t + 1]
        ac.append(_spearman(factor.loc[dt], factor.loc[nxt]))
        ac_dates.append(dt)
    return pd.Series(ac, index=ac_dates).dropna()


def factor_monotonicity(factor: pd.DataFrame, fwd_returns: pd.DataFrame, buckets: int = 10) -> Tuple[pd.Series, pd.Series]:
    """
    Returns: decile_spreads (Series) and average_decile_returns (Series of mean across time per decile)
    """
    common_dates = factor.index.intersection(fwd_returns.index)
    spreads = []
    spread_dates = []
    per_decile = {i: [] for i in range(buckets)}
    for dt in common_dates:
        fac = factor.loc[dt]
        ret = fwd_returns.loc[dt]
        aligned = pd.concat([fac, ret], axis=1, join="inner").dropna()
        if len(aligned) < buckets:
            continue
        aligned.columns = ["factor", "fwd_ret"]
        aligned["decile"] = pd.qcut(aligned["factor"], buckets, labels=False, duplicates="drop")
        decile_means = aligned.groupby("decile")["fwd_ret"].mean()
        for dec, val in decile_means.items():
            per_decile[dec].append(val)
        if not decile_means.empty:
            spreads.append(decile_means.max() - decile_means.min())
            spread_dates.append(dt)
    spread_series = pd.Series(spreads, index=spread_dates)
    avg_decile = pd.Series({dec: np.nanmean(vals) if len(vals) else np.nan for dec, vals in per_decile.items()})
    return spread_series.dropna(), avg_decile


def summarize_analytics(ic: pd.Series, ac: pd.Series, decile_spread: pd.Series, avg_decile: pd.Series) -> Dict[str, float]:
    mean_ic = ic.mean() if not ic.empty else np.nan
    ic_std = ic.std(ddof=1) if len(ic) > 1 else np.nan
    ic_tstat = mean_ic / (ic_std / np.sqrt(len(ic))) if len(ic) > 1 and ic_std and ic_std > 0 else np.nan
    ic_ir = mean_ic / ic_std if ic_std and ic_std > 0 else np.nan
    ic_hit_rate = (ic > 0).mean() if len(ic) else np.nan
    recent_ic_mean = ic.tail(60).mean() if len(ic) else np.nan

    summary = {
        "mean_ic": mean_ic,
        "ic_tstat": ic_tstat,
        "ic_ir": ic_ir,
        "ic_hit_rate": ic_hit_rate,
        "recent_ic_mean_60d": recent_ic_mean,
        "mean_autocorr": ac.mean() if not ac.empty else np.nan,
        "avg_decile_spread": decile_spread.mean() if not decile_spread.empty else np.nan,
    }
    for dec, val in avg_decile.items():
        summary[f"avg_decile_{dec}"] = val
    return summary


def update_registry(factor_name: str, summary: Dict[str, float], registry_path: Path | None = None) -> Path:
    registry = registry_path or factors_dir() / "factor_analytics_summary.parquet"
    registry.parent.mkdir(parents=True, exist_ok=True)
    if registry.exists():
        df = pd.read_parquet(registry)
        df = df[df["factor"] != factor_name]
    else:
        df = pd.DataFrame(columns=["factor"])
    row = {"factor": factor_name, **summary}
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_parquet(registry, index=False)
    logger.info("Updated factor registry at %s", registry)

    # Keep an in-repo reference copy for visibility/versioning (overwrites with latest).
    ref_dir = repo_root() / "diagnostics"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_parquet = ref_dir / "factor_analytics_summary.parquet"
    ref_csv = ref_dir / "factor_analytics_summary.csv"
    df.to_parquet(ref_parquet, index=False)
    df.to_csv(ref_csv, index=False)
    logger.info("Updated diagnostics reference registry at %s and %s", ref_parquet, ref_csv)
    return registry


def save_diagnostics(diagnostics: list[dict], path: Path | None = None) -> Path:
    """
    Legacy helper (no-op now). Kept for backward compatibility.
    """
    out_path = path or factors_dir() / "factor_step_diagnostics.parquet"
    logger.info("save_diagnostics skipped (step diagnostics disabled).")
    return out_path


def compute_all_analytics(
    factor: pd.DataFrame,
    fwd_returns: pd.DataFrame,
    buckets: int = 10,
    factor_name: str | None = None,
    registry_path: Path | None = None,
    write_registry: bool = False,
    run_ls_ptf: bool = True,
    top_pct: float = 0.1,
    bottom_pct: float = 0.1,
    ff_factors: pd.DataFrame | None = None,
) -> dict:
    """
    Convenience wrapper: compute IC, autocorrelation, monotonicity and summary.
    Optionally run a simple long-short diagnostic portfolio (equal-weighted top/bottom percentiles).
    Optionally write summary to registry if factor_name is provided and write_registry=True.
    """
    ic = information_coefficient(factor, fwd_returns)
    ac = factor_autocorrelation(factor)
    decile_spread, avg_decile = factor_monotonicity(factor, fwd_returns, buckets=buckets)
    summary = summarize_analytics(ic, ac, decile_spread, avg_decile)
    summary.update(_data_quality_stats(factor))
    # Add longer-window IC (12m ~ 252d) for weighting diagnostics
    ic_12m = ic.rolling(252).mean()
    summary["ic_mean_12m"] = ic_12m.iloc[-1] if len(ic_12m) else None
    summary["recent_ic_mean_60d"] = ic.rolling(60).mean().iloc[-1] if len(ic) else None

    ls_diag: dict = {}
    if run_ls_ptf:
        ls_diag = diagnostic_ls_backtest(
            factor,
            fwd_returns,
            top_pct=top_pct,
            bottom_pct=bottom_pct,
            ff_factors=ff_factors,
        )
        summary["ls_return_mean"] = ls_diag.get("ls_return_mean")
        summary["ls_return_std"] = ls_diag.get("ls_return_std")
        summary["ls_sharpe"] = ls_diag.get("ls_sharpe")
        summary["ls_max_drawdown"] = ls_diag.get("ls_max_drawdown")
        summary["ls_sharpe_last_yr"] = ls_diag.get("ls_sharpe_last_yr")
        summary["ls_max_drawdown_last_yr"] = ls_diag.get("ls_max_drawdown_last_yr")
        ff_reg = ls_diag.get("ff_regression") or {}
        for k, v in ff_reg.items():
            summary[f"ff_{k}"] = v

    if write_registry and factor_name:
        update_registry(factor_name, summary, registry_path=registry_path)
    return {
        "ic": ic,
        "autocorr": ac,
        "decile_spread": decile_spread,
        "avg_decile": avg_decile,
        "summary": summary,
        "ls_returns": ls_diag.get("ls_returns") if ls_diag else None,
        "ff_regression": ls_diag.get("ff_regression") if ls_diag else None,
    }


def compute_factor_correlation(scores: dict[str, pd.DataFrame], method: str = "pearson") -> pd.DataFrame:
    """
    Compute factor correlation matrix by stacking each factor (date x ticker) and correlating overlaps.
    """
    if not scores:
        return pd.DataFrame()
    stacked = []
    for name, df in scores.items():
        series = df.stack().rename(name)
        stacked.append(series)
    aligned = pd.concat(stacked, axis=1, join="inner").dropna(how="all")
    if aligned.empty:
        return pd.DataFrame()
    return aligned.corr(method=method)


def save_correlation_matrix(corr: pd.DataFrame, path: Path | None = None, ref_name: str = "factor_correlation") -> Path:
    out_path = path or factors_dir() / f"{ref_name}.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    corr.to_parquet(out_path)
    # Reference copies for quick inspection (Parquet + CSV) in diagnostics
    ref_dir = repo_root() / "diagnostics"
    ref_dir.mkdir(parents=True, exist_ok=True)
    corr.to_parquet(ref_dir / f"{ref_name}.parquet")
    corr.to_csv(ref_dir / f"{ref_name}.csv")
    logger.info("Saved factor correlation matrix to %s and diagnostics/%s.(parquet,csv)", out_path, ref_name)
    return out_path


def long_short_returns(
    factor: pd.DataFrame,
    fwd_returns: pd.DataFrame,
    top_pct: float = 0.1,
    bottom_pct: float = 0.1,
) -> pd.Series:
    """
    Construct a daily long-short return (top minus bottom percentile) using forward returns.
    Percentiles are specified as fractions (e.g., 0.1 = 10%).
    """
    if top_pct <= 0 or bottom_pct <= 0 or top_pct + bottom_pct >= 1:
        raise ValueError("top_pct and bottom_pct must be > 0 and sum to < 1.")

    common_dates = factor.index.intersection(fwd_returns.index)
    ls_ret: list[float] = []
    ls_dates: list = []
    for dt in common_dates:
        fac = factor.loc[dt]
        ret = fwd_returns.loc[dt]
        aligned = pd.concat([fac, ret], axis=1, join="inner").dropna()
        if aligned.empty:
            continue
        aligned.columns = ["factor", "fwd_ret"]
        long_cut = aligned["factor"].quantile(1 - top_pct)
        short_cut = aligned["factor"].quantile(bottom_pct)
        long_mask = aligned["factor"] >= long_cut
        short_mask = aligned["factor"] <= short_cut
        if long_mask.sum() == 0 or short_mask.sum() == 0:
            continue
        long_ret = aligned.loc[long_mask, "fwd_ret"].mean()
        short_ret = aligned.loc[short_mask, "fwd_ret"].mean()
        ls_ret.append(long_ret - short_ret)
        ls_dates.append(dt)
    return pd.Series(ls_ret, index=ls_dates)


def sharpe_ratio(returns: pd.Series, annualization: int = 252) -> float:
    if returns.empty:
        return np.nan
    r = returns.dropna()
    if r.empty:
        return np.nan
    vol = r.std(ddof=1)
    if vol == 0 or pd.isna(vol):
        return np.nan
    return np.sqrt(annualization) * r.mean() / vol


def max_drawdown(returns: pd.Series) -> float:
    """
    Maximum drawdown of the cumulative return series.
    """
    if returns.empty:
        return np.nan
    r = returns.dropna()
    if r.empty:
        return np.nan
    cumulative = (1 + r).cumprod()
    running_max = cumulative.cummax()
    drawdowns = cumulative / running_max - 1
    return drawdowns.min()


def diagnostic_ls_backtest(
    factor: pd.DataFrame,
    fwd_returns: pd.DataFrame,
    top_pct: float = 0.1,
    bottom_pct: float = 0.1,
    ff_factors: pd.DataFrame | None = None,
) -> dict:
    """
    Lightweight diagnostic: equal-weighted long-short portfolio using percentiles.
    Returns LS time series, Sharpe, max drawdown, and optional FF regression.
    """
    ls = long_short_returns(factor, fwd_returns, top_pct=top_pct, bottom_pct=bottom_pct)
    ls_mean = ls.mean()
    ls_std = ls.std(ddof=1)
    ls_sharpe = sharpe_ratio(ls)
    ls_mdd = max_drawdown(ls)
    recent = ls.tail(252)
    ls_sharpe_last_yr = sharpe_ratio(recent)
    ls_mdd_last_yr = max_drawdown(recent)
    ff_reg = regress_on_ff(ls, ff_factors) if ff_factors is not None else {}
    return {
        "ls_returns": ls,
        "ls_return_mean": ls_mean,
        "ls_return_std": ls_std,
        "ls_sharpe": ls_sharpe,
        "ls_max_drawdown": ls_mdd,
        "ls_sharpe_last_yr": ls_sharpe_last_yr,
        "ls_max_drawdown_last_yr": ls_mdd_last_yr,
        "ff_regression": ff_reg,
    }


def regress_on_ff(ls_returns: pd.Series, ff_factors: pd.DataFrame) -> Dict[str, float]:
    """
    Regress long-short returns on FF factors (mktrf, smb, hml, rmw, cma, umd).
    Returns alpha, betas, and t-stats (p-values when scipy is available).
    """
    if ls_returns.empty or ff_factors.empty:
        return {}
    y = pd.to_numeric(ls_returns, errors="coerce").dropna().sort_index()
    ff = ff_factors.copy()
    ff.columns = [c.lower() for c in ff.columns]
    cols = [c for c in ["mktrf", "smb", "hml", "rmw", "cma", "umd"] if c in ff.columns]
    if not cols:
        return {}
    df = ff[cols].apply(pd.to_numeric, errors="coerce")
    df = df.loc[df.index.intersection(y.index)]
    y = y.loc[y.index.intersection(df.index)]
    if y.empty or df.empty:
        return {}
    # Drop any remaining rows with NaNs to avoid dtype issues
    aligned = pd.concat([y, df], axis=1, join="inner").dropna()
    if aligned.empty:
        return {}
    y = aligned.iloc[:, 0]
    X = aligned.iloc[:, 1:].values.astype(float)
    X = np.column_stack([np.ones(len(X)), X]).astype(float)  # add intercept
    beta, *_ = np.linalg.lstsq(X, y.values, rcond=None)

    # Compute standard errors and t-stats
    n, k = X.shape
    resids = y.values - X @ beta
    dof = max(n - k, 1)
    sigma2 = np.dot(resids, resids) / dof
    xtx_inv = np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.diag(sigma2 * xtx_inv))
    tstats = beta / se

    from scipy import stats  # expect scipy to be available; surface error if not
    pvals = 2 * (1 - stats.t.cdf(np.abs(tstats), df=dof))

    res = {
        "alpha": beta[0],
        "t_alpha": tstats[0],
        "p_alpha": pvals[0],
    }
    for i, col in enumerate(cols, start=1):
        res[f"beta_{col}"] = beta[i]
        res[f"t_{col}"] = tstats[i]
        res[f"p_{col}"] = pvals[i]
    return res


def corr_with_ff(ls_returns: dict[str, pd.Series], ff_factors: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    """
    Correlate factor long-short returns with FF factor time series.
    Returns DataFrame indexed by factor name with FF columns.
    """
    if not ls_returns or ff_factors.empty:
        return pd.DataFrame()
    ff = ff_factors.copy()
    ff.columns = [c.lower() for c in ff.columns]
    cols = [c for c in ["mktrf", "smb", "hml", "rmw", "cma", "umd", "rf"] if c in ff.columns]
    if not cols:
        return pd.DataFrame()
    ff = ff[cols]
    rows = []
    index = []
    for name, series in ls_returns.items():
        aligned = pd.concat([series, ff], axis=1, join="inner").dropna()
        if aligned.empty:
            continue
        corr = aligned.corr(method=method).iloc[0, 1:]  # first column is ls_returns
        rows.append(corr)
        index.append(name)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows, index=index)
