from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, Tuple


def compute_forward_returns(open_px: pd.DataFrame, shift: int = 1) -> pd.DataFrame:
    """
    Open-to-open forward returns, shifted to avoid look-ahead.
    """
    fwd = open_px.shift(-shift) / open_px - 1.0
    return fwd


def apply_liquidity_filters(
    open_px: pd.DataFrame,
    volume: pd.DataFrame,
    price_min: float = 5.0,
    adv_lookback: int | None = None,
    adv_min: float | None = None,
) -> pd.DataFrame:
    """
    Filter universe: price > price_min and ADV > adv_min.
    Returns mask DataFrame (True where liquid).
    """
    price_filter = open_px > price_min
    if adv_lookback and adv_min:
        adv = volume.rolling(adv_lookback, min_periods=max(1, adv_lookback // 2)).mean()
        vol_filter = adv > adv_min
        return price_filter & vol_filter
    return price_filter


def _ridge_regression(X: np.ndarray, y: np.ndarray, alpha: float = 1.0) -> np.ndarray:
    """
    Closed-form ridge: (X'X + alpha I)^-1 X'y
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    # Drop any non-finite rows
    finite_mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X = X[finite_mask]
    y = y[finite_mask]
    if X.size == 0 or y.size == 0:
        return np.zeros(X.shape[1] if X.ndim == 2 else 0)
    # Drop zero-variance columns to avoid singularities
    col_var = X.var(axis=0)
    keep_cols = col_var > 0
    if not np.any(keep_cols):
        return np.zeros(X.shape[1])
    X_use = X[:, keep_cols]
    # Clip extreme values and replace inf/nan to keep matmul stable
    X_use = np.nan_to_num(np.clip(X_use, -1e6, 1e6))
    y = np.nan_to_num(np.clip(y, -1e6, 1e6))
    n_features = X.shape[1]
    XtX = X_use.T @ X_use
    if not np.isfinite(XtX).all():
        return np.zeros(n_features)
    ridge = XtX + alpha * np.eye(X_use.shape[1])
    ridge = np.clip(ridge, -1e12, 1e12)
    if not np.isfinite(ridge).all():
        return np.zeros(n_features)
    with np.errstate(all="ignore"):
        inv = np.linalg.pinv(ridge)
        beta_use = inv @ X_use.T @ y
    if not np.all(np.isfinite(beta_use)):
        return np.zeros(n_features)
    beta = np.zeros(n_features)
    beta[keep_cols] = beta_use
    return beta


def purify_cross_section(
    target: pd.Series,
    controls: pd.DataFrame,
    alpha: float = 1.0,
    min_coverage: float = 0.7,
) -> Tuple[pd.Series, dict]:
    """
    Cross-sectional ridge regression to purge sector/beta/size effects.
    Returns residuals (aligned to target index) and fitted betas.
    """
    # Align and drop NaNs
    t = target.copy()
    if t.name is None:
        t.name = "target"
    aligned = pd.concat([t, controls], axis=1, join="inner")
    aligned = aligned.replace([np.inf, -np.inf], np.nan).dropna()
    if aligned.empty:
        return pd.Series(index=target.index, dtype=float), {}
    # Coverage gate
    coverage = aligned.count() / len(aligned)
    use_cols = [c for c in controls.columns if coverage.get(c, 0) >= min_coverage]
    if not use_cols:
        return pd.Series(index=target.index, dtype=float), {}

    X = aligned[use_cols].astype(float).values
    y = aligned[t.name].astype(float).values
    # Bound magnitudes to keep matmul stable; infinities already dropped.
    X = np.clip(X, -1e6, 1e6)
    y = np.clip(y, -1e6, 1e6)
    beta = _ridge_regression(X, y, alpha=alpha)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        fitted = X @ beta
    resid = aligned[t.name] - fitted
    resid_full = pd.Series(index=target.index, dtype=float)
    resid_full.loc[aligned.index] = resid
    return resid_full, dict(zip(use_cols, beta))


def purge_factors(
    factors: Dict[str, pd.DataFrame],
    controls: Dict[str, pd.DataFrame],
    ridge_alpha: float,
    min_feature_coverage: float,
) -> Dict[str, pd.DataFrame]:
    """
    Purify each factor cross-sectionally against controls (sector/beta/size) per date.
    """
    out = {}
    for name, fac in factors.items():
        resids = []
        for dt, row in fac.iterrows():
            ctrl_df = pd.DataFrame({k: v.loc[dt] for k, v in controls.items() if dt in v.index})
            resid, _ = purify_cross_section(row, ctrl_df, alpha=ridge_alpha, min_coverage=min_feature_coverage)
            resids.append(resid)
        if resids:
            out[name] = pd.DataFrame(resids).sort_index()
    return out
