"""Independent known values and adverse cases for the bounded Q07 proxy."""
import json
import math
from copy import deepcopy

import numpy as np
import pytest

from systematic_alpha_lab.factor_research.beneish import (
    beneish_m_score,
    legacy_logistic_score,
    legacy_q07_quarterly_proxy,
)


def quarter(**changes):
    row = {
        "entity_id": "synthetic-company", "fiscal_year": 2020, "fiscal_quarter": 1,
        "currency": "USD", "unit": "million", "receivables": 10.0,
        "sales": 100.0, "cost_of_goods_sold": 60.0, "current_assets": 40.0,
        "net_ppe": 50.0, "total_assets": 100.0, "depreciation": 5.0,
        "sga_expense": 10.0, "long_term_debt": 10.0, "current_liabilities": 20.0,
    }
    return row | changes


def pair():
    return quarter(fiscal_quarter=2), quarter()


def test_published_sunbeam_displayed_ratios():
    # Independent source: Kelley School of Business's Sunbeam Example, p.3.
    # https://apps.kelley.iu.edu/Beneish/Content/Examples/SunbeamExample.pdf
    ratios = {"DSRI": 1.1670, "GMI": 0.3002, "AQI": 0.9282, "SGI": 1.1870,
              "DEPI": 1.2831, "SGAI": 0.5157, "TATA": 0.1050, "LVGI": 0.7955}
    result = beneish_m_score(ratios)
    assert result["calculation_ready"]
    assert result["reasons"] == []
    assert result["m_score"] == pytest.approx(-1.8840350, abs=1e-12)
    assert result["m_score"] == pytest.approx(-1.884, abs=5e-4)
    assert "probability" not in result


def test_known_quarterly_arithmetic_and_inputs_unchanged():
    current, previous = pair()
    original = deepcopy((current, previous))
    result = legacy_q07_quarterly_proxy(current, previous)
    assert result["calculation_ready"]
    assert result["ratios"] == {"DSRI": 1, "GMI": 1, "AQI": 1, "SGI": 1,
                                "DEPI": 1, "SGAI": 1, "TATA": 0, "LVGI": 1}
    assert result["m_score"] == pytest.approx(-2.48, abs=1e-12)
    assert result["legacy_logistic_score"] == pytest.approx(0.4353637081969708)
    assert result["flag"] is False
    assert result["metadata_status"] == "caller_declared_consistent"
    assert result["source_status"] == "not_certified"
    assert "probability" not in result
    assert (current, previous) == original


def test_tata_preserves_incomplete_q07_formula():
    current, previous = pair()
    current["current_assets"] = 45
    result = legacy_q07_quarterly_proxy(current, previous)
    assert result["ratios"]["TATA"] == pytest.approx(0.05)
    assert result["ratios"]["AQI"] == pytest.approx(0.5)
    assert result["m_score"] == pytest.approx(-2.44805, abs=1e-12)


def test_fiscal_year_rollover_is_allowed():
    result = legacy_q07_quarterly_proxy(quarter(), quarter(fiscal_year=2019, fiscal_quarter=4))
    assert result["calculation_ready"]


@pytest.mark.parametrize("change", [
    {"fiscal_quarter": 1}, {"fiscal_quarter": 3}, {"fiscal_year": 2019},
    {"fiscal_quarter": 2.5}, {"fiscal_quarter": True}, {"fiscal_quarter": np.bool_(True)},
    {"fiscal_year": np.bool_(True)}, {"fiscal_quarter": 5},
    {"entity_id": "other-company"}, {"entity_id": None},
])
def test_invalid_identity_or_period_never_produces_a_flag(change):
    current, previous = pair()
    result = legacy_q07_quarterly_proxy(current | change, previous)
    assert result["reasons"]
    assert result["m_score"] is None
    assert result["flag"] is None


def test_missing_previous_quarter():
    result = legacy_q07_quarterly_proxy(quarter(), None)
    assert result["flag"] is None
    assert result["reasons"] == ["missing_or_invalid_previous_quarter"]


@pytest.mark.parametrize("field,current,previous", [
    ("fiscal_quarter", quarter(fiscal_quarter=np.bool_(True)), quarter(fiscal_year=2019, fiscal_quarter=4)),
    ("fiscal_year", quarter(fiscal_year=np.bool_(True), fiscal_quarter=2), quarter(fiscal_year=1)),
])
def test_numpy_boolean_fiscal_labels_are_rejected_before_integer_coercion(field, current, previous):
    # Converting True to 1 would otherwise make both pairs consecutive.
    result = legacy_q07_quarterly_proxy(current, previous)
    assert f"invalid_numeric:current.{field}" in result["reasons"]
    assert result["flag"] is None


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf"), True, np.bool_(True)])
def test_missing_or_nonfinite_amounts_do_not_become_false(value):
    current, previous = pair()
    result = legacy_q07_quarterly_proxy(current | {"sales": value}, previous)
    assert result["reasons"]
    assert result["flag"] is None
    assert result["legacy_logistic_score"] is None


@pytest.mark.parametrize("side,field,value", [
    ("current", "sales", 0), ("previous", "receivables", 0),
    ("current", "total_assets", 0), ("current", "depreciation", 0),
    ("previous", "sga_expense", 0), ("previous", "current_assets", 50),
])
def test_zero_denominators_are_diagnosed(side, field, value):
    current, previous = pair()
    {"current": current, "previous": previous}[side][field] = value
    result = legacy_q07_quarterly_proxy(current, previous)
    assert any(reason.startswith("zero_denominator:") for reason in result["reasons"])
    assert result["flag"] is None


def test_valid_zero_numerators_and_debt_are_retained():
    current, previous = pair()
    current.update(receivables=0, sga_expense=0, long_term_debt=0)
    result = legacy_q07_quarterly_proxy(current, previous)
    assert result["calculation_ready"]
    assert result["ratios"]["DSRI"] == 0
    assert result["ratios"]["SGAI"] == 0


@pytest.mark.parametrize("field", ["currency", "unit"])
def test_missing_context_does_not_certify_inputs(field):
    current, previous = pair()
    del current[field]
    result = legacy_q07_quarterly_proxy(current, previous)
    assert result["calculation_ready"]
    assert result["metadata_status"] == "unverified"
    assert result["context_warnings"] == [f"missing_or_invalid_metadata:{field}"]
    assert result["source_status"] == "not_certified"


@pytest.mark.parametrize("field", ["currency", "unit"])
def test_declared_context_mismatch_rejects_pair(field):
    current, previous = pair()
    result = legacy_q07_quarterly_proxy(current | {field: "different"}, previous)
    assert result["flag"] is None
    assert f"metadata_mismatch:{field}" in result["reasons"]


def test_overflowing_intermediate_is_not_a_clipped_score():
    current, previous = pair()
    current.update(long_term_debt=1e308, current_liabilities=1e308)
    result = legacy_q07_quarterly_proxy(current, previous)
    assert result["flag"] is None
    assert "nonfinite_intermediate:LVGI" in result["reasons"]


@pytest.mark.parametrize("ratio_value", [None, math.nan, math.inf, math.inf * -1, True, np.bool_(True)])
def test_raw_ratio_failure_is_diagnosed(ratio_value):
    ratios = dict.fromkeys(("DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "TATA", "LVGI"), 1.0)
    result = beneish_m_score(ratios | {"GMI": ratio_value})
    assert result["m_score"] is None
    assert result["reasons"]


def test_raw_ratio_score_overflow_is_diagnosed():
    ratios = dict.fromkeys(("DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "TATA", "LVGI"), 1.0)
    result = beneish_m_score(ratios | {"TATA": 1e308})
    assert result["m_score"] is None
    assert result["reasons"] == ["nonfinite:m_score"]


def test_legacy_logistic_boundary_and_invalid_score():
    assert legacy_logistic_score(-2.22) == 0.5
    assert legacy_logistic_score(-2.22 - 1e-8) < 0.5
    assert legacy_logistic_score(-2.22 + 1e-8) > 0.5
    assert legacy_logistic_score(1e300) == 1.0
    assert legacy_logistic_score(-1e300) == pytest.approx(1 / (1 + math.exp(100)))
    assert legacy_logistic_score(math.inf) is None
    assert legacy_logistic_score(math.nan) is None


def test_flags_on_either_side_of_original_threshold():
    current, previous = pair()
    # Keep leverage unchanged while varying the explicitly legacy accrual term.
    for target, expected_flag in ((-2.22 - 1e-8, False), (-2.22 + 1e-8, True)):
        liabilities = 20 - 100 * (target + 2.48) / 4.679
        changed = current | {"current_liabilities": liabilities, "long_term_debt": 30 - liabilities}
        result = legacy_q07_quarterly_proxy(changed, previous)
        assert result["m_score"] == pytest.approx(target, abs=1e-12)
        assert result["flag"] is expected_flag


def test_all_returned_results_are_strict_json_serializable():
    current, previous = pair()
    variants = [current, current | {"sales": math.nan}, current | {"total_assets": 0},
                current | {"current_liabilities": 1e308, "long_term_debt": 1e308}]
    for row in variants:
        result = legacy_q07_quarterly_proxy(row, previous)
        assert json.loads(json.dumps(result, allow_nan=False)) == result
    invalid_ratios = beneish_m_score({"DSRI": math.inf})
    assert json.loads(json.dumps(invalid_ratios, allow_nan=False)) == invalid_ratios
