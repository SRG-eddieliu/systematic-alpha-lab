from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .data_loader import AlphaDataLoader, _resolve
from .preprocess import compute_forward_returns, apply_liquidity_filters, purify_cross_section
from .weighting import (
    weight_equal,
    weight_ic,
    weight_mlr,
    weight_bayesian_shrink,
    weight_gmv,
    weight_mvo,
)
from .evaluate import evaluate_alpha, rank_ic


def _prepare_controls(sector_map: pd.Series, beta: pd.Series, size: pd.Series, ff_row: Optional[pd.Series] = None) -> pd.DataFrame:
    ctrl = pd.DataFrame({"beta": pd.to_numeric(beta, errors="coerce"), "size": pd.to_numeric(size, errors="coerce")})
    # Sector dummies; merge tiny sectors into misc
    sector_counts = sector_map.value_counts()
    large = sector_counts[sector_counts >= 5].index
    sec = sector_map.where(sector_map.isin(large), "MISC")
    dummies = pd.get_dummies(sec, prefix="sector")
    ctrl = pd.concat([ctrl, dummies], axis=1)
    if ff_row is not None:
        ff_vals = pd.to_numeric(ff_row, errors="coerce")
        for name, val in ff_vals.items():
            ctrl[f"ff_{name.lower()}"] = val
    return ctrl


def _covariance(alphas: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    aligned = [a.stack().rename(name) for name, a in alphas.items()]
    if not aligned:
        return pd.DataFrame()
    mat = pd.concat(aligned, axis=1)
    return mat.cov()


def _train_xgb_alpha(features: pd.DataFrame, params: dict):
    try:
        from xgboost import XGBRegressor
    except Exception as exc:
        warnings.warn(f"xgboost unavailable ({exc}); skipping xgb model.")
        return None

    df = features.dropna()
    if df.empty or "ret" not in df.columns:
        return None
    dates = sorted(df["Date"].unique())
    train_win = params.get("train_window", 252)
    val_win = params.get("val_window", 30)
    if len(dates) < train_win + val_win + 1:
        return None

    preds = []

    base_params = {k: v for k, v in params.items() if k not in {"train_window", "val_window"}}
    for i in range(train_win + val_win, len(dates)):
        pred_date = dates[i]
        train_dates = dates[i - train_win - val_win : i - val_win]
        val_dates = dates[i - val_win : i]
        train = df[df["Date"].isin(train_dates)]
        val = df[df["Date"].isin(val_dates)]
        test = df[df["Date"] == pred_date]
        if train.empty or val.empty or test.empty:
            continue
        X_train = train.drop(columns=["Date", "Ticker", "ret"])
        y_train = train["ret"]
        X_val = val.drop(columns=["Date", "Ticker", "ret"])
        y_val = val["ret"]
        # skip tiny or constant training sets
        if len(train) < 30 or train["ret"].nunique() <= 1:
            continue
        model = XGBRegressor(**base_params)
        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        test_pred = model.predict(test.drop(columns=["Date", "Ticker", "ret"]))
        out = test[["Date", "Ticker"]].copy()
        out["pred"] = test_pred
        preds.append(out)

    if not preds:
        return None
    all_pred = pd.concat(preds)
    alpha = all_pred.pivot(index="Date", columns="Ticker", values="pred").sort_index()
    return alpha


def _train_sklearn_alpha(features: pd.DataFrame, model_cls, params: dict):
    df = features.dropna()
    if df.empty or "ret" not in df.columns:
        return None
    dates = sorted(df["Date"].unique())
    train_win = params.get("train_window", 252)
    val_win = params.get("val_window", 0)
    if len(dates) < train_win + val_win + 1:
        return None

    preds = []
    base_params = {k: v for k, v in params.items() if k not in {"train_window", "val_window"}}
    for i in range(train_win + val_win, len(dates)):
        pred_date = dates[i]
        train_dates = dates[i - train_win - val_win : i - val_win]
        if not train_dates:
            continue
        train = df[df["Date"].isin(train_dates)]
        test = df[df["Date"] == pred_date]
        if train.empty or test.empty:
            continue
        X_train = train.drop(columns=["Date", "Ticker", "ret"])
        y_train = train["ret"]
        model = model_cls(**base_params)
        model.fit(X_train, y_train)
        test_pred = model.predict(test.drop(columns=["Date", "Ticker", "ret"]))
        out = test[["Date", "Ticker"]].copy()
        out["pred"] = test_pred
        preds.append(out)

    if not preds:
        return None
    all_pred = pd.concat(preds)
    alpha = all_pred.pivot(index="Date", columns="Ticker", values="pred").sort_index()
    return alpha


def run_alpha_pipeline(
    cfg_path: str | Path,
    theta: Dict[str, pd.DataFrame],
    sector_map: pd.Series,
    beta_series: pd.DataFrame,
    size_series: pd.DataFrame,
    factors_for_ic: Optional[Dict[str, pd.DataFrame]] = None,
    pod_name: Optional[str] = None,
    raw_factors: Optional[Dict[str, pd.DataFrame]] = None,
    ml_methods: Optional[list[str]] = None,
) -> dict:
    """
    Orchestrates purification, weighting, and evaluation.
    - theta: dict of thematic composites (Date x Ticker)
    - sector_map: Series indexed by ticker with sector codes
    - beta_series: DataFrame (Date x Ticker) of betas
    - size_series: Series or DataFrame of size proxy (Date x Ticker)
    - factors_for_ic: optional raw/purified factors for IC weighting
    """
    cfg = json.loads(Path(cfg_path).read_text())
    loader = AlphaDataLoader(cfg)
    price = loader.load_price()
    volume = loader.load_volume()
    ff = loader.load_ff()

    # Universe filters
    liquid_mask = apply_liquidity_filters(price, volume, price_min=cfg["price_min"], adv_lookback=cfg["adv_lookback"], adv_min=cfg["adv_min"])
    price = price.where(liquid_mask)

    fwd = compute_forward_returns(price, shift=1)

    # Purify returns per date
    purged_returns_rows = []
    for dt, row in fwd.iterrows():
        size_row = size_series.loc[dt] if dt in size_series.index else size_series.iloc[-1]
        beta_row = beta_series.loc[dt] if dt in beta_series.index else beta_series.iloc[-1]
        ff_row = None
        if ff is not None and dt in ff.index:
            if ff.loc[dt].notna().mean() >= cfg.get("min_ff_coverage", 0.0):
                ff_row = ff.loc[dt]
        ctrl = _prepare_controls(sector_map, beta_row, size_row, ff_row=ff_row)
        resid, _ = purify_cross_section(row.rename("ret"), ctrl, alpha=cfg["purge_ridge_alpha"], min_coverage=cfg["min_feature_coverage"])
        resid.name = dt
        purged_returns_rows.append(resid)
    purged_returns = pd.DataFrame(purged_returns_rows).sort_index()

    # Purify theta
    purified_theta: Dict[str, pd.DataFrame] = {}
    for name, fac in theta.items():
        resids = []
        for dt, row in fac.iterrows():
            size_row = size_series.loc[dt] if dt in size_series.index else size_series.iloc[-1]
            beta_row = beta_series.loc[dt] if dt in beta_series.index else beta_series.iloc[-1]
            ff_row = None
            if ff is not None and dt in ff.index:
                if ff.loc[dt].notna().mean() >= cfg.get("min_ff_coverage", 0.0):
                    ff_row = ff.loc[dt]
            ctrl = _prepare_controls(sector_map, beta_row, size_row, ff_row=ff_row)
            resid, _ = purify_cross_section(row, ctrl, alpha=cfg["purge_ridge_alpha"], min_coverage=cfg["min_feature_coverage"])
            resid.name = dt
            resids.append(resid)
        if resids:
            purified_theta[name] = pd.DataFrame(resids).sort_index()

    purified_raw: Dict[str, pd.DataFrame] = {}
    if raw_factors:
        for name, fac in raw_factors.items():
            resids = []
            for dt, row in fac.iterrows():
                size_row = size_series.loc[dt] if dt in size_series.index else size_series.iloc[-1]
                beta_row = beta_series.loc[dt] if dt in beta_series.index else beta_series.iloc[-1]
                ff_row = None
                if ff is not None and dt in ff.index:
                    if ff.loc[dt].notna().mean() >= cfg.get("min_ff_coverage", 0.0):
                        ff_row = ff.loc[dt]
                ctrl = _prepare_controls(sector_map, beta_row, size_row, ff_row=ff_row)
                resid, _ = purify_cross_section(row, ctrl, alpha=cfg["purge_ridge_alpha"], min_coverage=cfg["min_feature_coverage"])
                resid.name = dt
                resids.append(resid)
            if resids:
                purified_raw[name] = pd.DataFrame(resids).sort_index()

    # Reindex to purged_returns index and forward-fill to boost overlap across dates
    if purged_returns is not None and not purged_returns.empty:
        for name, fac in list(purified_theta.items()):
            fac2 = fac.reindex(purged_returns.index).ffill()
            purified_theta[name] = fac2
        for name, fac in list(purified_raw.items()):
            fac2 = fac.reindex(purged_returns.index).ffill()
            purified_raw[name] = fac2

    # Weighting methods
    results = {}

    def build_feature_panel():
        panels = []
        for name, fac in purified_theta.items():
            panels.append(fac.stack().rename(name))
        for name, fac in purified_raw.items():
            panels.append(fac.stack().rename(name))
        if not panels:
            return None
        feat = pd.concat(panels, axis=1)
        feat.index = feat.index.set_names(["Date", "Ticker"])
        feat = feat.reset_index()
        return feat

    ml_methods = ml_methods or []
    ml_methods = [m for m in ml_methods if m]
    ml_requested = bool(ml_methods)
    ic_series_map: Dict[str, pd.Series] = {}
    ic_weights_by_date: Dict[pd.Timestamp, Dict[str, float]] = {}
    ic_alpha_rows = {}
    mlr_weights_by_date: Dict[pd.Timestamp, Dict[str, float]] = {}
    mlr_window = cfg.get("mlr_window", 252)
    mlr_ridge_alpha = cfg.get("mlr_ridge_alpha", 0.0)
    cov_window = cfg.get("cov_window", 252)
    gmv_weights_by_date: Dict[pd.Timestamp, Dict[str, float]] = {}
    gmv_alpha_rows = {}
    mvo_weights_by_date: Dict[pd.Timestamp, Dict[str, float]] = {}
    mvo_alpha_rows = {}

    # Equal weight (skipped if ml-only pod)
    if not ml_requested:
        ew_w = weight_equal(list(purified_theta.keys()))
        alpha_ew = sum(purified_theta[k] * w for k, w in ew_w.items())
        results["equal"] = {"weights": ew_w, "alpha": alpha_ew, "metrics": evaluate_alpha(alpha_ew, purged_returns)}

    # IC weights
    if not ml_requested:
        if factors_for_ic:
            for name, fac in factors_for_ic.items():
                ic_series_map[name] = rank_ic(fac, purged_returns)
        dates = list(purged_returns.index)
        ic_window = cfg.get("ic_window", 252)
        for dt in dates:
            w_raw = {}
            for name, s in ic_series_map.items():
                past = s[s.index < dt].dropna().tail(ic_window)
                if past.empty:
                    continue
                val = past.mean()
                if np.isfinite(val):
                    w_raw[name] = val
            total = sum(abs(v) for v in w_raw.values())
            if total == 0:
                continue
            w_norm = {k: v / total for k, v in w_raw.items()}
            ic_weights_by_date[dt] = w_norm
            if all(dt in fac.index for fac in purified_theta.values()):
                ic_alpha_rows[dt] = sum(
                    purified_theta[k].loc[dt].fillna(0) * w_norm.get(k, 0.0) for k in purified_theta
                )
        if ic_alpha_rows:
            alpha_ic = pd.DataFrame(ic_alpha_rows).T.sort_index()
            last_dt = sorted(ic_weights_by_date.keys())[-1]
            last_w = ic_weights_by_date[last_dt]
            results["ic_weight"] = {"weights": last_w, "alpha": alpha_ic, "metrics": evaluate_alpha(alpha_ic, purged_returns)}

    # MLR weights (stub: use last-date betas from regression of purged returns on theta)
    if not ml_requested:
        dates = list(purged_returns.index)
        X_cols = list(purified_theta.keys())
        if dates and X_cols:
            # Long panel for rolling fits
            panel = pd.concat(
                [purged_returns.stack().rename("ret")]
                + [fac.stack().rename(name) for name, fac in purified_theta.items()],
                axis=1,
                join="inner",
            ).dropna()
            alpha_rows = {}
            for i, dt in enumerate(dates):
                if i < mlr_window:
                    continue
                train_dates = dates[i - mlr_window : i]
                train = panel[panel.index.get_level_values(0).isin(train_dates)].dropna()
                if train.empty:
                    continue
                y = train["ret"].values
                X = train[X_cols].values
                if X.size == 0 or y.size == 0:
                    continue
                # Clip to keep matmul stable
                X = np.clip(X, -1e6, 1e6)
                y = np.clip(y, -1e6, 1e6)
                XtX = X.T @ X
                if not np.isfinite(XtX).all():
                    continue
                ridge = (mlr_ridge_alpha or 0.0) + 1e-6  # add tiny ridge for stability
                XtX = XtX + ridge * np.eye(X.shape[1])
                if not np.isfinite(XtX).all():
                    continue
                with np.errstate(all="ignore"):
                    try:
                        beta_vec = np.linalg.pinv(XtX) @ X.T @ y
                    except Exception:
                        continue
                mlr_w = weight_mlr(dict(zip(X_cols, beta_vec)))
                if not mlr_w:
                    continue
                mlr_weights_by_date[dt] = mlr_w
                alpha_rows[dt] = sum(
                    purified_theta[k].loc[dt].fillna(0) * mlr_w.get(k, 0.0)
                    for k in X_cols
                    if dt in purified_theta[k].index
                )
            if alpha_rows:
                alpha_mlr = pd.DataFrame(alpha_rows).T.sort_index()
                last_w = mlr_weights_by_date[sorted(mlr_weights_by_date.keys())[-1]]
                results["mlr"] = {"weights": last_w, "alpha": alpha_mlr, "metrics": evaluate_alpha(alpha_mlr, purged_returns)}

    # Bayesian shrink toward EW
    if not ml_requested and mlr_weights_by_date:
        lam = cfg.get("bayes_lambda", 0.5)
        bayes_rows = {}
        last_bayes_w = {}
        for dt, w_mlr in mlr_weights_by_date.items():
            bayes_w = weight_bayesian_shrink(w_mlr, ew_w, lam)
            last_bayes_w = bayes_w
            bayes_rows[dt] = sum(
                purified_theta[k].loc[dt].fillna(0) * bayes_w.get(k, 0.0)
                for k in purified_theta
                if dt in purified_theta[k].index
            )
        if bayes_rows:
            alpha_bayes = pd.DataFrame(bayes_rows).T.sort_index()
            results["bayesian"] = {"weights": last_bayes_w, "alpha": alpha_bayes, "metrics": evaluate_alpha(alpha_bayes, purged_returns)}

    # Risk parity / MVO (rolling, no look-ahead)
    if not ml_requested:
        dates = list(purged_returns.index)
        ic_window = cfg.get("ic_window", 252)
        for i, dt in enumerate(dates):
            if i < cov_window:
                continue
            window_dates = dates[i - cov_window : i]
            theta_window = {k: fac.loc[window_dates] for k, fac in purified_theta.items()}
            cov = _covariance(theta_window)
            if cov.empty:
                continue
            rp_w = weight_gmv(cov, use_abs=cfg.get("risk_parity_abs", True))
            if rp_w:
                gmv_weights_by_date[dt] = rp_w
                gmv_alpha_rows[dt] = sum(
                    purified_theta[k].loc[dt].fillna(0) * rp_w.get(k, 0.0) for k in purified_theta
                )
            mu = {}
            for name, s in ic_series_map.items():
                past = s[s.index < dt].dropna().tail(ic_window)
                if past.empty:
                    continue
                m = past.mean()
                if np.isfinite(m):
                    mu[name] = m
            mvo_w = weight_mvo(
                expected=mu,
                cov=cov,
                risk_aversion=cfg.get("mvo_risk_aversion", 5.0),
                long_only=cfg.get("mvo_long_only", True),
            )
            if mvo_w:
                mvo_weights_by_date[dt] = mvo_w
                mvo_alpha_rows[dt] = sum(
                    purified_theta[k].loc[dt].fillna(0) * mvo_w.get(k, 0.0) for k in purified_theta
                )
        if gmv_alpha_rows:
            alpha_rp = pd.DataFrame(gmv_alpha_rows).T.sort_index()
            last_w = gmv_weights_by_date[sorted(gmv_weights_by_date.keys())[-1]]
            results["gmv"] = {"weights": last_w, "alpha": alpha_rp, "metrics": evaluate_alpha(alpha_rp, purged_returns)}
        if mvo_alpha_rows:
            alpha_mvo = pd.DataFrame(mvo_alpha_rows).T.sort_index()
            last_w = mvo_weights_by_date[sorted(mvo_weights_by_date.keys())[-1]]
            results["mvo"] = {"weights": last_w, "alpha": alpha_mvo, "metrics": evaluate_alpha(alpha_mvo, purged_returns)}

    # XGB path (ml-only pod)
    if ml_requested:
        feat = build_feature_panel()
        if feat is not None:
            target = purged_returns.stack().rename("ret")
            target.index = target.index.set_names(["Date", "Ticker"])
            target = target.reset_index()
            feat = feat.merge(target, on=["Date", "Ticker"], how="inner")
            for method in ml_methods:
                if method == "xgb" and cfg.get("xgb_params"):
                    alpha_ml = _train_xgb_alpha(feat, cfg["xgb_params"])
                elif method == "rf" and cfg.get("rf_params"):
                    from sklearn.ensemble import RandomForestRegressor

                    alpha_ml = _train_sklearn_alpha(feat, RandomForestRegressor, cfg["rf_params"])
                elif method == "gbm" and cfg.get("gbm_params"):
                    from sklearn.ensemble import GradientBoostingRegressor

                    alpha_ml = _train_sklearn_alpha(feat, GradientBoostingRegressor, cfg["gbm_params"])
                elif method == "mlp" and cfg.get("mlp_params"):
                    from sklearn.neural_network import MLPRegressor

                    alpha_ml = _train_sklearn_alpha(feat, MLPRegressor, cfg["mlp_params"])
                else:
                    alpha_ml = None
                if alpha_ml is not None:
                    results[method] = {"weights": {}, "alpha": alpha_ml, "metrics": evaluate_alpha(alpha_ml, purged_returns)}

    # Save outputs
    out_dir = Path(cfg.get("output_dir", "outputs"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, res in results.items():
        alpha = res["alpha"]
        alpha_stack = alpha.stack().reset_index()
        alpha_stack.columns = ["date", "ticker", "alpha"]
        suffix = f"{pod_name}_" if pod_name else ""
        alpha_path = out_dir / f"alpha_{suffix}{name}.parquet"
        alpha_stack.to_parquet(alpha_path, index=False)
        res["alpha_path"] = alpha_path

    return results


def run_pod_grid(cfg_path: str | Path) -> dict:
    """
    Convenience to run all pods defined in config['pods'].
    Loads composites/factors using paths in config.
    """
    cfg = json.loads(Path(cfg_path).read_text())
    loader = AlphaDataLoader(cfg)
    # Controls
    co = pd.read_parquet(_resolve(cfg["sector_file"]))
    co.columns = co.columns.str.lower()
    sector_map = co.set_index("ticker")["sector"]
    beta_series = loader.load_factor(cfg["beta_factor"])
    size_series = loader.load_factor(cfg["size_factor"])

    pods = cfg.get("pods", {})
    all_results = {}
    diag_rows = []
    for pod_name, spec in pods.items():
        theta_names = spec.get("theta", [])
        theta = {}
        for n in theta_names:
            path = _resolve(cfg["factor_dir"]) / f"factor_{n}.parquet"
            if not path.exists():
                warnings.warn(f"Missing composite file for {n} at {path}; skipping.")
                continue
            comp = loader.load_composite(n)
            if n == "theta_info_forensic_drift":
                # This composite is sparse by construction (only updates around filings);
                # fill missing with 0 so it remains usable in ML feature panels.
                comp = comp.ffill().fillna(0)
            theta[n] = comp
        if not theta:
            warnings.warn(f"No composites loaded for pod {pod_name}; skipping.")
            continue
        raw_names = spec.get("raw_factors", [])
        raw_map = {}
        for n in raw_names:
            path = _resolve(cfg["factor_dir"]) / f"factor_{n}.parquet"
            if not path.exists():
                warnings.warn(f"Missing raw factor file for {n} at {path}; skipping.")
                continue
            raw_map[n] = loader.load_factor(n)
        ml_methods = spec.get("ml_methods")
        res = run_alpha_pipeline(
            cfg_path=cfg_path,
            theta=theta,
            sector_map=sector_map,
            beta_series=beta_series,
            size_series=size_series,
            factors_for_ic=theta,
            pod_name=pod_name,
            raw_factors=raw_map,
            ml_methods=ml_methods,
        )
        all_results[pod_name] = res
        for method, out in res.items():
            metrics = out.get("metrics", {})
            decay = metrics.get("decay", {}) if metrics else {}
            diag_rows.append(
                {
                    "pod": pod_name,
                    "method": method,
                    "ic": metrics.get("ic"),
                    "ir": metrics.get("ir"),
                    "turnover": metrics.get("turnover"),
                    "decay_5": decay.get(5),
                    "decay_10": decay.get(10),
                    "decay_21": decay.get(21),
                    "alpha_path": out.get("alpha_path"),
                }
            )
    if diag_rows:
        diag_dir = Path(__file__).resolve().parents[1] / "diagnostics"
        diag_dir.mkdir(parents=True, exist_ok=True)
        diag_df = pd.DataFrame(diag_rows)
        diag_df.to_csv(diag_dir / "alpha_metrics_all.csv", index=False)
    return all_results
