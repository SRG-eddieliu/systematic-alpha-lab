from systematic_alpha_lab.workflows import run_synthetic_equity_alpha_demo


def test_synthetic_equity_alpha_workflow_runs():
    data, factor_result, alpha_result = run_synthetic_equity_alpha_demo(n_days=120, n_assets=30, seed=11)

    assert data.prices.shape == (120, 30)
    assert set(factor_result.factors) == {"momentum_21d", "reversal_5d", "low_vol_21d"}
    assert set(factor_result.analytics) == set(factor_result.factors)
    assert alpha_result.alpha.shape[1] == 30
    assert "ic" in alpha_result.metrics
    assert "turnover" in alpha_result.metrics
