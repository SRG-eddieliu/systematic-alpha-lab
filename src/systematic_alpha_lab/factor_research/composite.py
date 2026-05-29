from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd

from .paths import repo_root, factors_dir
from .analytics import (
    compute_all_analytics,
    compute_factor_correlation,
    save_correlation_matrix,
    corr_with_ff,
)


def _load_composite_config() -> dict:
    cfg_path = repo_root() / "config" / "factors" / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text()) or {}
    except Exception:
        return {}


def ic_ir_map_from_analytics(analytics: dict, blend_12m: bool = False) -> dict:
    """
    Build {factor_name: ic_ir} from analytics dict returned by run_analytics_only or compute_all_analytics.
    If blend_12m=True and ic_mean_12m is available, return 0.5*ic_ir + 0.5*ic_mean_12m.
    """
    out = {}
    for name, res in analytics.items():
        summary = res.get("summary") or {}
        if blend_12m and summary.get("ic_mean_12m") is not None and summary.get("ic_ir") is not None:
            val = 0.5 * summary["ic_ir"] + 0.5 * summary["ic_mean_12m"]
        else:
            val = summary.get("ic_ir")
        if val is not None:
            out[name] = val
    return out


def ls_vol_map_from_analytics(analytics: dict) -> dict:
    """
    Build {factor_name: ls_return_std} from analytics dict (if LS run was enabled).
    """
    out = {}
    for name, res in analytics.items():
        summary = res.get("summary") or {}
        val = summary.get("ls_return_std")
        if val is not None:
            out[name] = val
    return out


def _compute_weights(
    factor_names: Iterable[str],
    factors: Dict[str, pd.DataFrame],
    method: str = "equal",
    ic_map: Optional[dict] = None,
    ls_vol_map: Optional[dict] = None,
) -> Dict[str, float]:
    names = list(factor_names)
    if not names:
        return {}
    method = (method or "equal").lower()
    weights = {}
    if method == "inv_vol":
        vols = {}
        # Prefer LS vol map if provided; fallback to factor std
        for n in names:
            v = None
            if ls_vol_map is not None:
                v = ls_vol_map.get(n)
            if v is None:
                df = factors.get(n)
                if df is not None:
                    v = np.nanstd(df.values)
            vols[n] = v
        for n, v in vols.items():
            if v and np.isfinite(v) and v > 0:
                weights[n] = 1.0 / v
    elif method == "ic_ir":
        ic_map = ic_map or {}
        for n in names:
            val = ic_map.get(n)
            if val is not None and np.isfinite(val):
                weights[n] = float(val)
    if not weights:
        # fallback: equal
        weights = {n: 1.0 for n in names}
    # normalize
    total = sum(abs(w) for w in weights.values())
    if total == 0:
        return {n: 1.0 / len(weights) for n in weights}
    return {k: v / total for k, v in weights.items()}


def build_composite(
    name: str,
    spec: dict,
    factors: Dict[str, pd.DataFrame],
    ic_map: Optional[dict] = None,
    ls_vol_map: Optional[dict] = None,
    default_method: str = "equal",
) -> pd.DataFrame:
    """
    Build a composite factor as a weighted average of existing factor DataFrames.
    spec expects:
      - factors: list of factor names
      - sign: optional dict of {factor: +1/-1}
      - weight_method: optional ("equal", "inv_vol", "ic_ir")
    Returns a wide Date x Ticker DataFrame.
    """
    factor_list = spec.get("factors", [])
    if not factor_list:
        return pd.DataFrame()
    sign_map = {k: float(v) for k, v in (spec.get("sign") or {}).items()}
    method = spec.get("weight_method", default_method)

    # Collect frames and union index/columns
    frames = {}
    all_index = None
    all_cols = None
    for fn in factor_list:
        df = factors.get(fn)
        if df is None:
            continue
        frames[fn] = df
        all_index = df.index if all_index is None else all_index.union(df.index)
        all_cols = df.columns if all_cols is None else all_cols.union(df.columns)
    if not frames:
        return pd.DataFrame()

    weights = _compute_weights(frames.keys(), frames, method=method, ic_map=ic_map, ls_vol_map=ls_vol_map)
    num = None
    den = None
    for fn, df in frames.items():
        adj = df.reindex(all_index).reindex(columns=all_cols)
        adj = adj * sign_map.get(fn, 1.0)
        w = weights.get(fn, 0.0)
        if num is None:
            num = adj * w
            den = adj.notna() * w
        else:
            num = num.add(adj * w, fill_value=0)
            den = den.add(adj.notna() * w, fill_value=0)
    comp = num.where(den != 0)
    comp = comp / den.replace(0, np.nan)
    if name == "theta_info_forensic_drift":
        # Sparse by construction (event-driven); forward-fill then zero-fill to keep cross-sections usable downstream.
        comp = comp.ffill().fillna(0)
    comp.name = name
    return comp


def build_composites_from_config(
    factors: Dict[str, pd.DataFrame],
    ic_map: Optional[dict] = None,
    ls_vol_map: Optional[dict] = None,
    override_method: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Build all composites defined under config/config.json -> \"composites\".
    Supports optional override_method to test different weighting (equal/inv_vol/ic_ir).
    """
    cfg = _load_composite_config()
    composites_cfg = cfg.get("composites", {})
    out = {}
    for name, spec in composites_cfg.items():
        spec = dict(spec) if spec else {}
        if override_method:
            spec["weight_method"] = override_method
        comp = build_composite(name, spec, factors, ic_map=ic_map, ls_vol_map=ls_vol_map)
        if not comp.empty:
            out[name] = comp
    return out


def save_composite_analytics(df: pd.DataFrame, name: str = "composite_analytics") -> dict:
    """
    Save composite analytics (wide DataFrame) to diagnostics in both parquet and CSV.
    Returns paths.
    """
    diag_dir = repo_root() / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = diag_dir / f"{name}.parquet"
    csv_path = diag_dir / f"{name}.csv"
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    return {"parquet": parquet_path, "csv": csv_path}


def save_composite_factor(name: str, df: pd.DataFrame) -> dict:
    """
    Persist a composite factor to the factors directory (wide -> long parquet),
    mirroring raw factor outputs.
    """
    factors_dir().mkdir(parents=True, exist_ok=True)
    long_df = df.stack().reset_index()
    long_df.columns = ["Date", "Ticker", "Value"]
    long_df = long_df.dropna(subset=["Value"])
    long_df["Date"] = pd.to_datetime(long_df["Date"]).dt.date
    parquet_path = factors_dir() / f"factor_{name}.parquet"
    long_df.to_parquet(parquet_path, index=False)
    return {"parquet": parquet_path}


def save_composite_ls(name: str, ls: pd.Series) -> dict:
    """
    Persist composite long/short returns to the factors directory for reuse.
    """
    factors_dir().mkdir(parents=True, exist_ok=True)
    df = ls.reset_index()
    df.columns = ["Date", "LS_Return"]
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    parquet_path = factors_dir() / f"ls_{name}.parquet"
    df.to_parquet(parquet_path, index=False)
    return {"parquet": parquet_path}


def analyze_composites(
    composites: Dict[str, pd.DataFrame],
    fwd_returns: pd.DataFrame,
    ff: Optional[pd.DataFrame] = None,
    min_dates: int = 60,
) -> dict:
    """
    Compute full analytics for composites and save summary/correlations to diagnostics.
    Returns dict with analytics per composite and paths to saved artifacts.
    """
    analytics = {}
    summary_rows = []
    ls_returns = {}
    factor_paths = {}
    ls_paths = {}
    for name, fac in composites.items():
        valid_dates = fac.dropna(how="all").index.nunique()
        if valid_dates < min_dates:
            logger.warning("Skipping analytics for %s: only %d valid dates (min %d)", name, valid_dates, min_dates)
            continue
        res = compute_all_analytics(
            fac,
            fwd_returns,
            factor_name=name,
            write_registry=False,
            ff_factors=ff,
        )
        analytics[name] = res
        summary_rows.append({"factor": name, **(res.get("summary") or {})})
        # Save composite factor and LS series similar to raw factors
        factor_paths[name] = save_composite_factor(name, fac)
        if res.get("ls_returns") is not None:
            ls_returns[name] = res["ls_returns"]
            ls_paths[name] = save_composite_ls(name, res["ls_returns"])

    paths = {}
    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        paths["summary"] = save_composite_analytics(summary_df, name="composite_analytics_summary")

    # Correlation among composites
    if composites:
        corr = compute_factor_correlation(composites)
        if not corr.empty:
            diag_dir = repo_root() / "diagnostics"
            diag_dir.mkdir(parents=True, exist_ok=True)
            corr_path = save_correlation_matrix(
                corr,
                path=diag_dir / "composite_correlation.parquet",
                ref_name="composite_correlation",
            )
            paths["correlation"] = corr_path

    # Correlation of composite LS with FF (if LS available)
    if ff is not None and ls_returns:
            ff_corr = corr_with_ff(ls_returns, ff)
            if not ff_corr.empty:
                diag_dir = repo_root() / "diagnostics"
                diag_dir.mkdir(parents=True, exist_ok=True)
                ff_corr_path = save_correlation_matrix(
                    ff_corr,
                    path=diag_dir / "composite_ff_correlation.parquet",
                    ref_name="composite_ff_correlation",
                )
                paths["ff_correlation"] = ff_corr_path

    if factor_paths:
        paths["factor_files"] = factor_paths
    if ls_paths:
        paths["ls_files"] = ls_paths

    return {"analytics": analytics, "paths": paths}


def run_composite_pipeline(
    factors: Dict[str, pd.DataFrame],
    fwd_returns: pd.DataFrame,
    ff: Optional[pd.DataFrame] = None,
    ic_map: Optional[dict] = None,
    ls_vol_map: Optional[dict] = None,
    weight_method: Optional[str] = None,
    min_dates: int = 60,
) -> dict:
    """
    Convenience: build composites (optionally overriding weight_method) and run full analytics,
    saving summary/correlation outputs to diagnostics.
    Returns {"composites": ..., "analytics": ..., "paths": ...}.
    """
    composites = build_composites_from_config(
        factors, ic_map=ic_map, ls_vol_map=ls_vol_map, override_method=weight_method
    )
    analysis = analyze_composites(composites, fwd_returns, ff=ff, min_dates=min_dates)
    return {"composites": composites, **analysis}


def select_best_weights(
    weight_runs: Dict[str, dict],
    criterion: str = "ic_ir",
) -> Dict[str, str]:
    """
    Given {weight_method: run_result} where run_result['analytics'][name]['summary'][criterion],
    pick the best weight_method per composite.
    Returns {composite_name: best_method}.
    """
    scores = {}
    for method, run in weight_runs.items():
        for name, res in (run.get("analytics") or {}).items():
            val = (res.get("summary") or {}).get(criterion)
            if val is None:
                continue
            scores.setdefault(name, {})[method] = val
    best = {}
    for comp, d in scores.items():
        if not d:
            continue
        best_method = max(d.items(), key=lambda kv: kv[1] if kv[1] is not None else -1e9)[0]
        best[comp] = best_method
    return best
