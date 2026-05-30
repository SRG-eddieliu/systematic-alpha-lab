from __future__ import annotations

import numpy as np
import pandas as pd

from systematic_alpha_lab.alpha import compute_forward_returns, evaluate_alpha
from systematic_alpha_lab.core import AlphaResearchResult, DataBundle, FactorResearchResult
from systematic_alpha_lab.factor_research.analytics import compute_all_analytics
from systematic_alpha_lab.factor_research.transforms import clean_factor


def make_synthetic_equity_data(
    n_days: int = 504,
    n_assets: int = 80,
    seed: int = 7,
) -> DataBundle:
    """
    Create a small synthetic equity panel with a weak embedded momentum effect.

    The data is not meant to be market-realistic. It exists so reviewers can run
    the research workflow without credentials or external data files.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    tickers = [f"STK{i:03d}" for i in range(n_assets)]

    market = rng.normal(0.0002, 0.01, size=n_days)
    sector_ids = np.array([f"Sector{idx % 8}" for idx in range(n_assets)])
    sector_shocks = rng.normal(0.0, 0.006, size=(n_days, 8))
    idio = rng.normal(0.0, 0.018, size=(n_days, n_assets))

    returns = np.zeros((n_days, n_assets))
    returns[0] = market[0] + sector_shocks[0, np.arange(n_assets) % 8] + idio[0]
    for t in range(1, n_days):
        weak_momentum = 0.04 * returns[t - 1]
        returns[t] = market[t] + sector_shocks[t, np.arange(n_assets) % 8] + idio[t] + weak_momentum

    prices = 100.0 * pd.DataFrame(1.0 + returns, index=dates, columns=tickers).cumprod()
    fwd_returns = compute_forward_returns(prices, shift=1)
    sectors = pd.Series(sector_ids, index=tickers, name="sector")

    return DataBundle(
        prices=prices,
        returns_forward=fwd_returns,
        sectors=sectors,
        metadata={"n_days": n_days, "n_assets": n_assets, "seed": seed},
    )


def build_simple_factors(data: DataBundle) -> dict[str, pd.DataFrame]:
    """Build a compact factor set from synthetic prices."""
    returns = data.prices.pct_change()
    raw = {
        "momentum_21d": data.prices.pct_change(21),
        "reversal_5d": -data.prices.pct_change(5),
        "low_vol_21d": -returns.rolling(21).std(),
    }
    return {
        name: clean_factor(factor, sector_map=data.sectors, min_coverage=0.5)
        for name, factor in raw.items()
    }


def evaluate_factors(data: DataBundle, factors: dict[str, pd.DataFrame]) -> FactorResearchResult:
    """Run lightweight factor analytics against forward returns."""
    analytics = {}
    for name, factor in factors.items():
        result = compute_all_analytics(
            factor,
            data.returns_forward,
            factor_name=name,
            write_registry=False,
            run_ls_ptf=True,
        )
        analytics[name] = {
            "mean_ic": result["summary"].get("mean_ic"),
            "ic_ir": result["summary"].get("ic_ir"),
            "ls_sharpe": result["summary"].get("ls_sharpe"),
            "dq_mean_coverage": result["summary"].get("dq_mean_coverage"),
        }
    return FactorResearchResult(factors=factors, analytics=analytics)


def build_alpha(factors: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combine simple factor scores into a single alpha score."""
    weights = {
        "momentum_21d": 0.50,
        "reversal_5d": 0.25,
        "low_vol_21d": 0.25,
    }
    alpha = None
    for name, factor in factors.items():
        contribution = factor * weights.get(name, 0.0)
        alpha = contribution if alpha is None else alpha.add(contribution, fill_value=0.0)
    return alpha


def run_synthetic_equity_alpha_demo(
    n_days: int = 504,
    n_assets: int = 80,
    seed: int = 7,
) -> tuple[DataBundle, FactorResearchResult, AlphaResearchResult]:
    """
    Run a credential-free mini workflow:

    synthetic data -> factor cleaning -> factor analytics -> alpha evaluation.
    """
    data = make_synthetic_equity_data(n_days=n_days, n_assets=n_assets, seed=seed)
    factors = build_simple_factors(data)
    factor_result = evaluate_factors(data, factors)
    alpha = build_alpha(factors)
    metrics = evaluate_alpha(alpha, data.returns_forward)
    alpha_result = AlphaResearchResult(
        alpha=alpha,
        metrics={
            "ic": metrics["ic"],
            "ir": metrics["ir"],
            "turnover": metrics["turnover"],
            "decay": metrics["decay"],
        },
        metadata={"weights": {"momentum_21d": 0.50, "reversal_5d": 0.25, "low_vol_21d": 0.25}},
    )
    return data, factor_result, alpha_result
