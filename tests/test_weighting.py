"""Coefficient arithmetic and covariance contracts, not portfolio validation."""

import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.alpha.weighting import (
    weight_bayesian_shrink,
    weight_equal,
    weight_gmv,
    weight_gmv_direction,
    weight_ic,
    weight_mlr,
    weight_mvo,
    weight_mvo_direction,
)


def covariance(values=((1.0, 2.0), (2.0, 9.0))):
    return pd.DataFrame(values, index=["A", "B"], columns=["A", "B"])


def test_equal_ic_regression_and_linear_shrink_have_hand_calculated_values():
    assert weight_equal(["A", "B"]) == {"A": 0.5, "B": 0.5}
    ic = {"A": pd.Series([99.0, 0.2, 0.4]), "B": pd.Series([99.0, -0.1, -0.1])}
    weights = weight_ic(ic, window=2)
    assert weights["A"] == pytest.approx(0.75) and weights["B"] == pytest.approx(-0.25)
    assert weight_mlr({"A": 3.0, "B": -1.0}) == {"A": 0.75, "B": -0.25}
    assert weight_bayesian_shrink({"A": 0.75, "B": -0.25}, {"A": 0.5, "B": 0.5}, 0.5) == {"A": 0.625, "B": 0.125}


def test_signed_normalization_does_not_overflow_finite_coefficients():
    assert weight_mlr({"A": 1e308, "B": -1e308}) == {"A": 0.5, "B": -0.5}


def test_gmv_direction_is_distinct_from_long_only_minimum_variance():
    cov = covariance()
    signed = weight_gmv_direction(cov, use_abs=False)
    assert signed["A"] == pytest.approx(7 / 6) and signed["B"] == pytest.approx(-1 / 6)
    absolute = weight_gmv_direction(cov)
    assert absolute["A"] == pytest.approx(7 / 8) and absolute["B"] == pytest.approx(1 / 8)
    weights = np.array(list(absolute.values()))
    # The feasible all-A allocation has less variance than this absolute-value heuristic.
    assert weights @ cov.to_numpy() @ weights > cov.loc["A", "A"]
    assert weight_gmv(cov) == absolute


def test_covariance_column_order_cannot_change_weights():
    cov = covariance()
    before = cov.copy(deep=True)
    for operation in (weight_gmv_direction, lambda frame: weight_mvo_direction({"A": 1.0, "B": 2.0}, frame)):
        assert operation(cov) == operation(cov[["B", "A"]])
    pd.testing.assert_frame_equal(cov, before)


def test_mvo_direction_matches_diagonal_example_and_clips_before_normalizing():
    cov = covariance(((1.0, 0.0), (0.0, 4.0)))
    expected = {"A": 1.0, "B": 2.0}
    weights = weight_mvo_direction(expected, cov, ridge=0)
    assert weights["A"] == pytest.approx(2 / 3) and weights["B"] == pytest.approx(1 / 3)
    assert weight_mvo_direction({"A": -1.0, "B": 2.0}, cov, ridge=0) == {"A": 0.0, "B": 1.0}
    signed = weight_mvo_direction({"A": -1.0, "B": 2.0}, cov, long_only=False, ridge=0)
    assert signed["A"] == pytest.approx(-2 / 3) and signed["B"] == pytest.approx(1 / 3)


def test_legacy_risk_aversion_is_explicitly_invariant_after_normalization():
    cov = covariance(((1.0, 0.0), (0.0, 4.0)))
    expected = {"A": 1.0, "B": 2.0}
    for scale in (1e-200, 1.0, 5.0, 1e200):
        assert weight_mvo(expected, cov, risk_aversion=scale) == weight_mvo_direction(expected, cov)


def test_singular_and_zero_directions_are_not_replaced_with_fallback_weights():
    assert weight_gmv_direction(covariance(((1.0, 1.0), (1.0, 1.0)))) == {"A": 0.5, "B": 0.5}
    zero = covariance(((0.0, 0.0), (0.0, 0.0)))
    assert weight_gmv_direction(zero) == {}
    assert weight_mvo_direction({"A": 0.0, "B": 0.0}, zero) == {}
    assert weight_mvo_direction({}, zero) == {}
    assert weight_equal([]) == {} and weight_mlr({}) == {}


@pytest.mark.parametrize("issue", ["rows", "columns", "labels", "nonsquare", "asymmetric", "indefinite", "nonfinite"])
def test_invalid_covariances_are_rejected_instead_of_silently_misaligning(issue):
    cov = covariance()
    if issue == "rows":
        cov.index = ["A", "A"]
    if issue == "columns":
        cov.columns = ["A", "A"]
    if issue == "labels":
        cov.columns = ["A", "C"]
    if issue == "nonsquare":
        cov = cov.iloc[:1]
    if issue == "asymmetric":
        cov.loc["A", "B"] = 1.0
    if issue == "indefinite":
        cov = covariance(((1.0, 2.0), (2.0, 1.0)))
    if issue == "nonfinite":
        cov.loc["A", "A"] = np.inf
    for operation in (weight_gmv_direction, lambda frame: weight_mvo_direction({"A": 1.0}, frame)):
        with pytest.raises(ValueError):
            operation(cov)


@pytest.mark.parametrize("value", [0, -1, True, np.nan, np.inf, "5"])
def test_invalid_legacy_risk_scaling_is_rejected(value):
    with pytest.raises(ValueError):
        weight_mvo({"A": 1.0}, covariance(), risk_aversion=value)


@pytest.mark.parametrize("value", [-1, True, np.inf, np.nan])
def test_invalid_regularization_is_rejected(value):
    with pytest.raises(ValueError):
        weight_mvo_direction({"A": 1.0}, covariance(), ridge=value)


@pytest.mark.parametrize("value", [-0.1, 1.1, True, np.nan])
def test_invalid_shrink_fraction_is_rejected(value):
    with pytest.raises(ValueError):
        weight_bayesian_shrink({}, {}, value)


@pytest.mark.parametrize("value", [0, -1, 2.5, True])
def test_invalid_ic_window_is_rejected(value):
    with pytest.raises(ValueError):
        weight_ic({}, value)


def test_invalid_coefficient_names_values_and_ic_order_are_rejected():
    with pytest.raises(ValueError):
        weight_equal(["A", "A"])
    with pytest.raises(ValueError):
        weight_mlr({"A": np.nan})
    with pytest.raises(ValueError):
        weight_mlr({"": 1.0})
    with pytest.raises(ValueError):
        weight_ic({"A": pd.Series([0.1, 0.2], index=[2, 1])}, 2)
    with pytest.raises(ValueError):
        weight_ic({"A": pd.Series([0.1, np.inf])}, 2)
