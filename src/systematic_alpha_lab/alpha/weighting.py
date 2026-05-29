from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, Optional


def weight_equal(names: list[str]) -> Dict[str, float]:
    n = len(names)
    if n == 0:
        return {}
    w = 1.0 / n
    return {k: w for k in names}


def weight_ic(ic_series: Dict[str, pd.Series], window: int) -> Dict[str, float]:
    weights = {}
    for name, s in ic_series.items():
        if s is None or s.empty:
            continue
        rolling = s.dropna().tail(window)
        if rolling.empty:
            continue
        val = rolling.mean()
        if np.isfinite(val):
            weights[name] = val
    total = sum(abs(v) for v in weights.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in weights.items()}


def weight_mlr(betas: Dict[str, float]) -> Dict[str, float]:
    total = sum(abs(v) for v in betas.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in betas.items()}


def weight_bayesian_shrink(mlr_weights: Dict[str, float], ew_weights: Dict[str, float], lam: float) -> Dict[str, float]:
    return {k: lam * mlr_weights.get(k, 0.0) + (1 - lam) * ew_weights.get(k, 0.0) for k in ew_weights}


def weight_gmv(cov: pd.DataFrame, use_abs: bool = True) -> Dict[str, float]:
    """
    Generalized minimum variance (GMV) weights: w ∝ Σ^-1 * 1, optionally forced long-only via abs().
    This is a variance-minimizing mix; it is not a full ERC/RP solve.
    """
    if cov.empty:
        return {}
    try:
        inv = np.linalg.pinv(cov.values)
    except Exception:
        return {}
    ones = np.ones(len(cov))
    w = inv @ ones
    if use_abs:
        w = np.abs(w)
    total = w.sum()
    if total == 0:
        return {}
    w = w / total
    return dict(zip(cov.index, w))


def weight_mvo(expected: Dict[str, float], cov: pd.DataFrame, risk_aversion: float = 5.0, long_only: bool = True, ridge: float = 1e-6) -> Dict[str, float]:
    """
    Mean-variance optimal weights (w ∝ (Σ + ridge I)^-1 * μ / λ).
    - expected: dict of expected returns per factor (e.g., mean IC).
    - cov: covariance matrix of factor values.
    - risk_aversion: larger = more variance penalty.
    - long_only: clip negatives to 0 if True.
    """
    if not expected or cov.empty:
        return {}
    names = [n for n in cov.index if n in expected and n in cov.columns]
    if not names:
        return {}
    mu = np.array([expected[n] for n in names], dtype=float)
    finite_mask = np.isfinite(mu)
    if not finite_mask.any():
        return {}
    mu = mu[finite_mask]
    names = [n for i, n in enumerate(names) if finite_mask[i]]
    sub_cov = cov.loc[names, names].copy()
    if ridge:
        sub_cov = sub_cov + np.eye(len(names)) * ridge
    try:
        inv = np.linalg.pinv(sub_cov.values)
    except Exception:
        return {}
    w = inv @ mu
    if risk_aversion and risk_aversion > 0:
        w = w / risk_aversion
    if long_only:
        w = np.clip(w, 0, None)
    total = np.sum(np.abs(w))
    if total == 0:
        return {}
    w = w / total
    return dict(zip(names, w))
