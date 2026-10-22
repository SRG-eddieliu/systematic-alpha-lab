"""Hand-calculated diagnostics; no historical investment-performance claims."""

import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.factor_research.analytics import (
    _data_quality_stats,
    compute_all_analytics,
    factor_monotonicity,
    long_short_returns,
    max_drawdown,
)


def panel(values):
    return pd.DataFrame([values], index=pd.DatetimeIndex(["2020-01-31"]))


def test_bucket_spread_keeps_the_predeclared_factor_direction():
    spread, buckets = factor_monotonicity(panel([1, 2, 3, 4]), panel([.04, .03, .02, .01]), buckets=2)
    assert spread.iloc[0] == pytest.approx(-.02)
    np.testing.assert_allclose(buckets, [.035, .015])


def test_middle_bucket_is_not_selected_after_observing_returns():
    spread, buckets = factor_monotonicity(
        panel([1, 2, 3, 4, 5, 6]), panel([.01, .01, .9, .9, .03, .03]), buckets=3
    )
    assert spread.iloc[0] == pytest.approx(.02)
    np.testing.assert_allclose(buckets, [.01, .9, .03])


@pytest.mark.parametrize("missing_column", [False, True])
def test_missing_future_return_does_not_change_formation_buckets(missing_column):
    factor = panel(range(1, 9))
    returns = panel([.01, .02, .03, .04, .05, .06, .07, np.nan])
    if missing_column:
        returns = returns.drop(columns=7)
    spread, buckets = factor_monotonicity(factor, returns, buckets=4)
    np.testing.assert_allclose(buckets.iloc[:3], [.015, .035, .055])
    assert pd.isna(buckets.iloc[3])
    assert spread.index.equals(factor.index) and spread.isna().all()
    complete = returns.copy()
    complete[7] = .08
    _, complete_buckets = factor_monotonicity(factor, complete, buckets=4)
    pd.testing.assert_series_equal(buckets.iloc[:3], complete_buckets.iloc[:3])


def test_missing_selected_long_return_is_not_replaced_with_a_survivor():
    factor = panel([1, 2, 3, 4, 5])
    result = long_short_returns(factor, panel([.01, .02, .03, .04, np.nan]), top_pct=.2, bottom_pct=.2)
    assert result.index.equals(factor.index)
    assert result.isna().all()


def test_missing_unselected_return_does_not_change_long_short_diagnostic():
    result = long_short_returns(
        panel([1, 2, 3, 4, 5]), panel([.01, .02, np.nan, .04, .05]), top_pct=.2, bottom_pct=.2
    )
    assert result.iloc[0] == pytest.approx(.04)


def test_missing_return_column_does_not_shrink_selected_legs():
    result = long_short_returns(
        panel([1, 2, 3, 4, 5]), panel([.01, .02, .03, .04]), top_pct=.2, bottom_pct=.2
    )
    assert result.isna().all()


def test_tied_scores_cannot_put_the_same_asset_in_both_legs():
    factor, returns = panel([1] * 8), panel(np.arange(8) / 100)
    assert long_short_returns(factor, returns).isna().all()
    spread, buckets = factor_monotonicity(factor, returns, buckets=4)
    assert spread.index.equals(factor.index) and spread.isna().all()
    assert buckets.isna().all()


def test_collapsed_quantile_bins_do_not_masquerade_as_requested_buckets():
    spread, buckets = factor_monotonicity(panel([0] * 6 + [1] * 2), panel(np.arange(8) / 100), buckets=4)
    assert spread.isna().all()
    assert buckets.index.tolist() == [0, 1, 2, 3]
    assert buckets.isna().all()


def test_undefined_cross_sections_remain_visible_in_both_diagnostics():
    factor = pd.DataFrame([[np.nan] * 4, [1, 2, 3, 4], [1, 2, 3, 4]])
    returns = pd.DataFrame([[.01] * 4, [.01] * 4, [np.nan] * 4])
    spread, buckets = factor_monotonicity(factor, returns, buckets=2)
    result = long_short_returns(factor, returns)
    for series in (spread, result):
        assert series.index.tolist() == [0, 1, 2]
        np.testing.assert_allclose(series, [np.nan, 0., np.nan], equal_nan=True)
    np.testing.assert_allclose(buckets, [.01, .01])


def test_coverage_includes_empty_dates_and_permanently_missing_assets():
    result = _data_quality_stats(pd.DataFrame([[1., np.nan, np.nan], [np.nan] * 3]))
    assert result["dq_total_dates"] == 2
    assert result["dq_total_tickers"] == 3
    assert result["dq_non_null_obs"] == 1
    assert result["dq_pct_non_null"] == pytest.approx(1 / 6)
    assert result["dq_mean_coverage"] == pytest.approx(1 / 6)
    assert result["dq_min_coverage"] == 0
    assert result["dq_pct_allnan_dates"] == .5


def test_all_missing_panel_has_zero_coverage():
    result = _data_quality_stats(pd.DataFrame(np.nan, index=range(2), columns=range(3)))
    assert result["dq_total_dates"] == 2 and result["dq_total_tickers"] == 3
    assert result["dq_pct_non_null"] == 0 and result["dq_mean_coverage"] == 0
    assert result["dq_pct_allnan_dates"] == 1


@pytest.mark.parametrize("shape", [(0, 3), (2, 0), (0, 0)])
def test_empty_panel_preserves_declared_axis_counts(shape):
    result = _data_quality_stats(pd.DataFrame(index=range(shape[0]), columns=range(shape[1])))
    assert result["dq_total_dates"] == shape[0]
    assert result["dq_total_tickers"] == shape[1]
    assert result["dq_non_null_obs"] == 0
    assert pd.isna(result["dq_pct_non_null"])
    assert pd.isna(result["dq_pct_allnan_dates"])


@pytest.mark.parametrize("which", ["factor", "returns"])
@pytest.mark.parametrize("issue", ["infinity", "duplicate_date", "duplicate_asset", "null_date", "null_asset"])
def test_ambiguous_panels_are_rejected(which, issue):
    factor = pd.DataFrame([[1., 2., 3., 4.], [4., 3., 2., 1.]], index=[0, 1])
    returns = factor / 100
    target = factor if which == "factor" else returns
    if issue == "infinity":
        target.iloc[0, 0] = np.inf
    elif issue == "duplicate_date":
        target.index = [0, 0]
    elif issue == "duplicate_asset":
        target.columns = [0, 0, 2, 3]
    elif issue == "null_date":
        target.index = [0, None]
    elif issue == "null_asset":
        target.columns = [0, 1, 2, None]
    for operation in (factor_monotonicity, long_short_returns):
        with pytest.raises(ValueError):
            operation(factor, returns)


@pytest.mark.parametrize("buckets", [True, 0, 1, 2.5, np.nan])
def test_invalid_bucket_count_is_rejected(buckets):
    with pytest.raises(ValueError, match="buckets"):
        factor_monotonicity(panel([1, 2, 3, 4]), panel([.01] * 4), buckets=buckets)


@pytest.mark.parametrize("top,bottom", [(True, .1), (np.nan, .1), (.1, np.inf), (0, .1), (.5, .5)])
def test_invalid_long_short_fractions_are_rejected(top, bottom):
    with pytest.raises(ValueError):
        long_short_returns(panel([1, 2, 3, 4]), panel([.01] * 4), top_pct=top, bottom_pct=bottom)


@pytest.mark.parametrize("returns,expected", [([-.1, .05], -.1), ([-.1, -.1], -.19), ([.1, -.2, -.5], -.6)])
def test_drawdown_includes_initial_unit_wealth(returns, expected):
    assert max_drawdown(pd.Series(returns)) == pytest.approx(expected)


def test_wrapper_exposes_corrected_direction_and_retains_inputs():
    factor = panel([1., 2., 3., 4.])
    returns = panel([.04, .03, .02, .01])
    before_factor, before_returns = factor.copy(deep=True), returns.copy(deep=True)
    result = compute_all_analytics(factor, returns, buckets=2, run_ls_ptf=True)
    assert result["summary"]["avg_decile_spread"] == pytest.approx(-.02)
    assert result["summary"]["bucket_spread_observed_dates"] == 1
    assert result["summary"]["bucket_spread_missing_dates"] == 0
    pd.testing.assert_frame_equal(factor, before_factor)
    pd.testing.assert_frame_equal(returns, before_returns)
