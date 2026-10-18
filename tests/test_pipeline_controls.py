"""Availability-time controls: causal selection, bounded staleness and real pipeline replay."""
import json

import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.alpha.pipeline import (
    _control_history, _control_row_asof, run_alpha_pipeline,
)


def test_asof_sorts_history_and_never_selects_future():
    frame = pd.DataFrame({"A": [99., 1.]}, index=pd.to_datetime(["2026-01-10", "2026-01-01"]))
    history = _control_history(frame, "beta")
    assert _control_row_asof(history, pd.Timestamp("2026-01-03"), pd.Timedelta(days=2), "beta").A == 1.
    with pytest.raises(ValueError, match="Stale"):
        _control_row_asof(history, pd.Timestamp("2026-01-04"), pd.Timedelta(days=2), "beta")
    with pytest.raises(ValueError, match="No beta"):
        _control_row_asof(history, pd.Timestamp("2025-12-31"), pd.Timedelta(days=30), "beta")


@pytest.mark.parametrize("index", [pd.to_datetime(["2026-01-01", "2026-01-01"]), pd.to_datetime(["2026-01-01", None])])
def test_ambiguous_control_times_are_rejected(index):
    with pytest.raises(ValueError, match="unique and non-null"):
        _control_history(pd.DataFrame({"A": [1., 2.]}, index=index), "size")


@pytest.fixture
def pipeline_case(tmp_path):
    rng = np.random.default_rng(32)
    dates = pd.bdate_range("2026-01-01", periods=12)
    assets = [f"A{i:02d}" for i in range(40)]
    prices = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, .01, (12, 40)), axis=0)), index=dates, columns=assets)
    data = prices.stack().rename("open").reset_index()
    data.columns = ["date", "ticker", "open"]
    data["volume"] = 100000
    data.to_parquet(tmp_path / "prices.parquet", index=False)
    cfg = {"price_file": str(tmp_path / "prices.parquet"), "ff_file": str(tmp_path / "missing.parquet"),
           "output_dir": str(tmp_path / "output"), "price_min": 5, "adv_lookback": None, "adv_min": None,
           "purge_ridge_alpha": 1., "min_feature_coverage": .7, "cov_window": 252, "mlr_window": 252}
    path = tmp_path / "config.json"
    theta = {"signal": pd.DataFrame(rng.normal(size=(12, 40)), index=dates, columns=assets)}
    raw = {"raw": pd.DataFrame(rng.normal(size=(12, 40)), index=dates, columns=assets)}
    sectors = pd.Series([f"S{i // 10}" for i in range(40)], index=assets)
    controls = {name: pd.DataFrame(rng.normal(size=(12, 40)), index=dates, columns=assets) for name in ["beta", "size"]}
    def run(selected, age=None):
        options = dict(cfg)
        if age is not None:
            options["control_max_age_days"] = age
        path.write_text(json.dumps(options))
        return run_alpha_pipeline(path, theta, sectors, selected["beta"], selected["size"], raw_factors=raw)["equal"]["alpha"]
    return dates, controls, run


@pytest.mark.parametrize("name", ["beta", "size"])
def test_future_controls_cannot_change_earlier_alpha(pipeline_case, name):
    dates, controls, run = pipeline_case
    # Sparse history forces the formerly leaking missing-date branch for both controls.
    sparse = {key: frame.iloc[[0, -1]].copy() for key, frame in controls.items()}
    before = run(sparse, 30)
    altered = {key: frame.copy() for key, frame in sparse.items()}
    altered[name].iloc[-1] *= 100
    after = run(altered, 30)
    assert before.loc[before.index < dates[-1]].notna().any().any()
    pd.testing.assert_frame_equal(before.loc[before.index < dates[-1]], after.loc[after.index < dates[-1]])


@pytest.mark.parametrize("name", ["beta", "size"])
def test_pipeline_rejects_future_only_and_missing_exact_controls(pipeline_case, name):
    _, controls, run = pipeline_case
    selected = dict(controls)
    selected[name] = controls[name].iloc[-1:]
    with pytest.raises(ValueError, match=f"No {name}"):
        run(selected, 30)
    selected[name] = controls[name].iloc[[0, -1]]
    with pytest.raises(ValueError, match=f"Stale {name}"):
        run(selected)  # Exact-time matching is the default.


@pytest.mark.parametrize("age", [-1, float("nan"), True, "30"])
def test_invalid_staleness_policy_is_rejected(pipeline_case, age):
    _, controls, run = pipeline_case
    with pytest.raises(ValueError, match="control_max_age_days"):
        run(controls, age)


def test_pod_grid_loads_real_controls_with_no_selected_pods(tmp_path):
    from systematic_alpha_lab.alpha.pipeline import run_pod_grid
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    pd.DataFrame({"ticker": ["A"], "sector": ["S"]}).to_parquet(tmp_path / "sectors.parquet", index=False)
    for name in ["beta", "size"]:
        pd.DataFrame({"Date": dates, "Ticker": ["A", "A"], "Value": [1., 2.]}).to_parquet(tmp_path / f"factor_{name}.parquet", index=False)
    cfg = {"sector_file": str(tmp_path / "sectors.parquet"), "factor_dir": str(tmp_path),
           "beta_factor": "beta", "size_factor": "size", "pods": {}}
    path = tmp_path / "pod-config.json"
    path.write_text(json.dumps(cfg))
    assert run_pod_grid(path) == {}
