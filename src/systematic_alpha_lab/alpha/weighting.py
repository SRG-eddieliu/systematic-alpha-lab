from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np
import pandas as pd


def _names(names):
    if any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != len(names):
        raise ValueError("Weight names must be unique nonempty strings")


def _real(value, name, *, minimum=None, strictly_positive=False):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite and numeric")
    if (minimum is not None and value < minimum) or (strictly_positive and value <= 0):
        raise ValueError(f"Invalid {name} range")
    return float(value)


def _coefficients(values):
    _names(list(values))
    return {name: _real(value, "coefficient") for name, value in values.items()}


def _unit_gross(values):
    """Normalize signed coefficients without overflowing their absolute sum."""
    if not values:
        return {}
    scale = max(abs(value) for value in values.values())
    if scale == 0:
        return {}
    scaled = {name: value / scale for name, value in values.items()}
    gross = math.fsum(abs(value) for value in scaled.values())
    return {name: value / gross for name, value in scaled.items()}


def _covariance(cov):
    if not isinstance(cov, pd.DataFrame):
        raise TypeError("Covariance must be a DataFrame")
    _names(list(cov.index))
    _names(list(cov.columns))
    if set(cov.index) != set(cov.columns):
        raise ValueError("Covariance row and column labels must match")
    aligned = cov.loc[cov.index, cov.index].astype(float)
    matrix = aligned.to_numpy()
    if not np.isfinite(matrix).all():
        raise ValueError("Covariance must be finite")
    if not matrix.size:
        return aligned
    scale = np.max(np.abs(matrix))
    tolerance = 10 * np.finfo(float).eps * len(matrix) * scale
    if np.max(np.abs(matrix - matrix.T)) > tolerance:
        raise ValueError("Covariance must be symmetric")
    symmetric = matrix / 2 + matrix.T / 2
    if np.linalg.eigvalsh(symmetric).min() < -tolerance:
        raise ValueError("Covariance must be positive semidefinite")
    return pd.DataFrame(symmetric, index=aligned.index, columns=aligned.columns)


def _inverse_direction(cov, target):
    cutoff = 10 * np.finfo(float).eps * max(1, len(cov))
    direction = np.linalg.pinv(cov.to_numpy(), rcond=cutoff, hermitian=True) @ target
    if not np.isfinite(direction).all():
        raise ValueError("Covariance direction exceeds the finite numeric range")
    return direction


def weight_equal(names: list[str]) -> dict[str, float]:
    _names(names)
    n = len(names)
    if n == 0:
        return {}
    w = 1.0 / n
    return {k: w for k in names}


def weight_ic(ic_series: dict[str, pd.Series], window: int) -> dict[str, float]:
    """Normalize means of the last nonmissing IC observations supplied by the caller."""
    if isinstance(window, bool) or not isinstance(window, Integral) or window < 1:
        raise ValueError("window must be a positive integer")
    _names(list(ic_series))
    weights = {}
    for name, s in ic_series.items():
        if s is None or s.empty:
            continue
        if not s.index.is_unique or s.index.hasnans or not s.index.is_monotonic_increasing:
            raise ValueError("IC observations require ordered, unique, non-null timestamps")
        rolling = pd.to_numeric(s, errors="raise").dropna().tail(window)
        if rolling.empty:
            continue
        if not np.isfinite(rolling).all():
            raise ValueError("IC observations must be finite or missing")
        val = rolling.mean()
        if np.isfinite(val):
            weights[name] = val
    return _unit_gross(weights)


def weight_mlr(betas: dict[str, float]) -> dict[str, float]:
    return _unit_gross(_coefficients(betas))


def weight_bayesian_shrink(mlr_weights: dict[str, float], ew_weights: dict[str, float], lam: float) -> dict[str, float]:
    """Linear mixture on the explicit equal-weight universe, without renormalization."""
    lam = _real(lam, "lam", minimum=0)
    if lam > 1:
        raise ValueError("lam must be between zero and one")
    mlr_weights, ew_weights = _coefficients(mlr_weights), _coefficients(ew_weights)
    return {k: lam * mlr_weights.get(k, 0.0) + (1 - lam) * ew_weights.get(k, 0.0) for k in ew_weights}


def weight_gmv_direction(cov: pd.DataFrame, use_abs: bool = True) -> dict[str, float]:
    """Sum-normalized pseudoinverse direction, optionally taking absolute values.

    Absolute values are a coefficient heuristic, not constrained minimum variance
    or risk parity. Singular covariances do not establish a GMV optimum either.
    """
    if not isinstance(use_abs, bool):
        raise TypeError("use_abs must be boolean")
    cov = _covariance(cov)
    if cov.empty:
        return {}
    w = _inverse_direction(cov, np.ones(len(cov)))
    if use_abs:
        w = np.abs(w)
    scale = np.max(np.abs(w))
    if scale == 0:
        return {}
    w = w / scale
    total = math.fsum(w)
    if total == 0:
        return {}
    w = w / total
    if not np.isfinite(w).all():
        raise ValueError("Normalized covariance direction exceeds finite numeric range")
    return dict(zip(cov.index, w))


def weight_mvo_direction(
    expected: dict[str, float], cov: pd.DataFrame, long_only: bool = True, ridge: float = 1e-6
) -> dict[str, float]:
    """Unit-gross regularized covariance direction, optionally clipping negatives.

    Uses expected coefficients whose names occur in the covariance. This is not
    a constrained mean-variance optimizer; positive risk scaling cancels under
    the final normalization, so this explicit API has no risk-aversion argument.
    """
    if not isinstance(long_only, bool):
        raise TypeError("long_only must be boolean")
    ridge = _real(ridge, "ridge", minimum=0)
    expected = _coefficients(expected)
    cov = _covariance(cov)
    if not expected or cov.empty:
        return {}
    names = [n for n in cov.index if n in expected and n in cov.columns]
    if not names:
        return {}
    mu = np.array([expected[n] for n in names], dtype=float)
    sub_cov = cov.loc[names, names].copy()
    if ridge:
        sub_cov = sub_cov + np.eye(len(names)) * ridge
    if not np.isfinite(sub_cov.to_numpy()).all():
        raise ValueError("Regularized covariance exceeds the finite numeric range")
    w = _inverse_direction(sub_cov, mu)
    if long_only:
        w = np.clip(w, 0, None)
    return _unit_gross(dict(zip(names, w)))


def weight_gmv(cov: pd.DataFrame, use_abs: bool = True) -> dict[str, float]:
    """Compatibility name for :func:`weight_gmv_direction`, a coefficient heuristic."""
    return weight_gmv_direction(cov, use_abs=use_abs)


def weight_mvo(
    expected: dict[str, float],
    cov: pd.DataFrame,
    risk_aversion: float = 5.0,
    long_only: bool = True,
    ridge: float = 1e-6,
) -> dict[str, float]:
    """Compatibility wrapper; positive risk_aversion has no effect on unit-gross weights.

    Use weight_mvo_direction for an API without the misleading scale argument.
    A constrained optimizer with effective risk aversion is a separate component.
    """
    _real(risk_aversion, "risk_aversion", strictly_positive=True)
    return weight_mvo_direction(expected, cov, long_only=long_only, ridge=ridge)
