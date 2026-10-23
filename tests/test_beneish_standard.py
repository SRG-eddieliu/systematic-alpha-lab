"""Independent public arithmetic, frozen annual policy, and adversarial inputs."""
import json
import math
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from systematic_alpha_lab.factor_research.beneish_standard import (
    DEFINITION_ID,
    POSITIVE_FIELDS,
    REQUIRED_FIELDS_CURRENT,
    REQUIRED_FIELDS_PREVIOUS,
    annual_beneish,
)

ROOT = Path(__file__).resolve().parents[1]


def annual(year=2021, **changes):
    row = {
        "entity_id": "synthetic-company", "fiscal_year": year, "period_type": "annual", "flow_basis": "annual",
        "period_start": f"{year}-01-01", "period_end": f"{year}-12-31", "currency": "USD", "unit_scale": 1,
        "reporting_scope": "synthetic-consolidated", "accounting_basis": "synthetic-us-gaap",
        "trade_receivables_net": 10, "current_assets": 40, "current_liabilities": 20, "total_assets": 100,
        "net_ppe": 40, "sales": 100, "cost_of_goods_sold": 60, "depreciation": 10, "sga_expense": 10,
        "long_term_debt_noncurrent": 10, "income_before_extraordinary_items": 10, "operating_cash_flow": 10,
        "field_statuses": dict.fromkeys(REQUIRED_FIELDS_CURRENT, "verified_exact"),
    }
    return row | changes


def pair():
    return annual(), annual(2020)


def assert_invalid(result):
    assert result["reasons"]
    assert result["m_score"] is None
    assert result["flag"] is None
    assert result["calculation_ready"] is False
    assert result["standard_definition_satisfied"] is False
    assert result["research_ready"] is False
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_required_fields_agree_with_frozen_contract():
    contract = json.loads((ROOT / "docs/integrity-research-contract-v1.json").read_text())["beneish"]
    fields = contract["financial_fields"]
    assert set(REQUIRED_FIELDS_CURRENT) == {x["name"] for x in fields if "t" in x["periods"]}
    assert set(REQUIRED_FIELDS_PREVIOUS) == {x["name"] for x in fields if "p" in x["periods"]}
    assert len(REQUIRED_FIELDS_CURRENT) + len(REQUIRED_FIELDS_PREVIOUS) == contract["required_amount_count"] == 22
    assert DEFINITION_ID == contract["definition_id"]


def test_public_sunbeam_raw_amounts_against_independent_decimal_oracle():
    fixture = json.loads((ROOT / "docs/fixtures/beneish-sunbeam-1997.json").read_text())
    fields = json.loads((ROOT / "docs/integrity-research-contract-v1.json").read_text())["beneish"]["financial_fields"]
    names = {x["symbol"]: x["name"] for x in fields}
    # Dates, currency/units and declarations below are SYNTHETIC API context.
    # The published monetary inputs are not an authenticated historical vintage.
    rows = []
    for key, year in (("current", 1997), ("prior", 1996)):
        rows.append(annual(year, currency="SYNTHETIC", reporting_scope="synthetic-example-context",
                           accounting_basis="synthetic-example-context",
                           **{names[k]: v for k, v in fixture[key].items()}))
    result = annual_beneish(*rows)
    c, p = ({k: Decimal(v) for k, v in fixture[key].items()} for key in ("current", "prior"))
    expected = {
        "DSRI": c["AR"] * p["Sales"] / (p["AR"] * c["Sales"]),
        "GMI": (p["Sales"] - p["COGS"]) * c["Sales"] / ((c["Sales"] - c["COGS"]) * p["Sales"]),
        "AQI": (c["TA"] - c["CA"] - c["PPE"]) * p["TA"] / ((p["TA"] - p["CA"] - p["PPE"]) * c["TA"]),
        "SGI": c["Sales"] / p["Sales"],
        "DEPI": p["Dep"] * (c["Dep"] + c["PPE"]) / (c["Dep"] * (p["Dep"] + p["PPE"])),
        "SGAI": c["SGA"] * p["Sales"] / (p["SGA"] * c["Sales"]),
        "TATA": (c["IBEI"] - c["CFO"]) / c["TA"],
        "LVGI": (c["CL"] + c["LTD"]) * p["TA"] / ((p["CL"] + p["LTD"]) * c["TA"]),
    }
    coefficients = dict(zip(expected, map(Decimal, (".920", ".528", ".404", ".892", ".115", "-.172", "4.679", "-.327"))))
    score = Decimal("-4.840") + sum(coefficients[k] * v for k, v in expected.items())
    assert result["calculation_ready"]
    for name, value in expected.items():
        assert result["ratios"][name] == pytest.approx(float(value), rel=0, abs=1e-12)
        assert result["ratios"][name] == pytest.approx(float(fixture["published_ratios"][name]), rel=0, abs=5e-5)
    assert result["m_score"] == pytest.approx(float(score), rel=0, abs=1e-12)
    assert result["m_score"] == pytest.approx(-1.8841840767415738, rel=0, abs=1e-12)
    assert result["m_score"] == pytest.approx(float(fixture["published_m_score"]), rel=0, abs=5e-4)


def test_neutral_case_and_declarations_do_not_certify_sources_or_timing():
    current, previous = pair()
    original = deepcopy((current, previous))
    result = annual_beneish(current, previous)
    assert result["ratios"] == {"DSRI": 1, "GMI": 1, "AQI": 1, "SGI": 1, "DEPI": 1,
                                "SGAI": 1, "TATA": 0, "LVGI": 1}
    assert result["m_score"] == pytest.approx(-2.480, rel=0, abs=1e-12)
    assert result["calculation_ready"] and result["standard_definition_satisfied"]
    assert result["standard_definition_scope"] == "supplied_declarations_only"
    assert result["source_status"] == "not_certified_by_calculator"
    assert result["timing_status"] == "not_assessed"
    assert result["research_ready"] is False
    assert result["reference_screen"]["enabled"] is False and result["flag"] is None
    assert not any("probability" in key or "logistic" in key for key in result)
    assert result["reasons"] == []
    assert (current, previous) == original
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_asymmetric_hand_calculation_and_reference_screen():
    current = annual(trade_receivables_net=30, sales=200, cost_of_goods_sold=100, current_assets=60,
                     net_ppe=60, total_assets=200, depreciation=5, sga_expense=30,
                     current_liabilities=40, long_term_debt_noncurrent=40,
                     income_before_extraordinary_items=30, operating_cash_flow=10)
    result = annual_beneish(current, annual(2020), reference_screen=True)
    expected = {"DSRI": Fraction(3, 2), "GMI": Fraction(4, 5), "AQI": Fraction(2), "SGI": Fraction(2),
                "DEPI": Fraction(13, 5), "SGAI": Fraction(3, 2), "TATA": Fraction(1, 10), "LVGI": Fraction(4, 3)}
    assert result["ratios"] == pytest.approx({k: float(v) for k, v in expected.items()}, rel=0, abs=1e-12)
    assert result["m_score"] == pytest.approx(float(Fraction(-3727, 10000)), rel=0, abs=1e-12)
    assert result["reference_screen"]["enabled"] is True and result["flag"] is True


def test_optional_prior_income_cashflow_and_extras_do_not_affect_pair():
    current, previous = pair()
    expected = annual_beneish(current, previous)
    del previous["income_before_extraordinary_items"], previous["operating_cash_flow"]
    previous["field_statuses"] = dict.fromkeys(REQUIRED_FIELDS_PREVIOUS, "verified_exact")
    assert annual_beneish(current, previous) == expected
    previous.update(income_before_extraordinary_items=math.nan, operating_cash_flow=True, source_version="unexamined")
    current["unrelated_provider_field"] = object()
    assert annual_beneish(current, previous) == expected
    # The pair API does not claim to examine duplicate versions elsewhere.


@pytest.mark.parametrize("scale", [Decimal("0.01"), 10, 1000000])
def test_common_amount_scaling_and_mapping_order_are_invariant(scale):
    current, previous = pair()
    current.update(income_before_extraordinary_items=30, operating_cash_flow=-10)
    expected = annual_beneish(current, previous)
    scaled = []
    for row, fields in ((current, REQUIRED_FIELDS_CURRENT), (previous, REQUIRED_FIELDS_PREVIOUS)):
        changed = deepcopy(row)
        for field in fields:
            changed[field] = str(Decimal(str(row[field])) * Decimal(str(scale)))
        changed["unit_scale"] = str(Decimal(1) / Decimal(str(scale)))
        scaled.append(dict(reversed(list(changed.items()))))
    result = annual_beneish(*scaled)
    assert result["ratios"] == pytest.approx(expected["ratios"], rel=0, abs=1e-12)
    assert result["m_score"] == pytest.approx(expected["m_score"], rel=0, abs=1e-12)


@pytest.mark.parametrize("side,fields", [("current", REQUIRED_FIELDS_CURRENT), ("previous", REQUIRED_FIELDS_PREVIOUS)])
def test_every_required_amount_and_its_exact_declaration_are_required(side, fields):
    for field in fields:
        current, previous = pair()
        row = {"current": current, "previous": previous}[side]
        del row[field]
        result = annual_beneish(current, previous, reference_screen=True)
        assert_invalid(result)
        assert f"missing:{side}.{field}" in result["reasons"]
        for status in (None, "proxy", "unverified", True, ["verified_exact"]):
            current, previous = pair()
            {"current": current, "previous": previous}[side]["field_statuses"][field] = status
            result = annual_beneish(current, previous)
            assert_invalid(result)
            assert f"unverified_field:{side}.{field}" in result["reasons"]


@pytest.mark.parametrize("side", ["current", "previous"])
@pytest.mark.parametrize("field", POSITIVE_FIELDS)
@pytest.mark.parametrize("value", [0, -0.0, -1])
def test_positive_domain_is_enforced_for_both_periods(side, field, value):
    current, previous = pair()
    {"current": current, "previous": previous}[side][field] = value
    result = annual_beneish(current, previous, reference_screen=True)
    assert_invalid(result)
    assert f"nonpositive:{side}.{field}" in result["reasons"]


@pytest.mark.parametrize("value", [None, math.nan, math.inf, -math.inf, True, np.bool_(True), "bad", [], {}, 1 + 2j])
@pytest.mark.parametrize("field", ["sales", "income_before_extraordinary_items", "unit_scale", "fiscal_year"])
def test_invalid_required_scalar_never_produces_nonfinite_json_or_flag(field, value):
    current, previous = pair()
    assert_invalid(annual_beneish(current | {field: value}, previous, reference_screen=True))


@pytest.mark.parametrize("field", ["income_before_extraordinary_items", "operating_cash_flow"])
@pytest.mark.parametrize("value", ["1e-9999", Decimal("-1e-9999")])
def test_nonzero_signed_amount_cannot_underflow_to_zero_on_conversion(field, value):
    current, previous = pair()
    result = annual_beneish(current | {field: value}, previous)
    assert_invalid(result)
    assert f"underflow_numeric:current.{field}" in result["reasons"]


def test_zero_debt_and_signed_income_cashflow_are_valid():
    current, previous = pair()
    current.update(long_term_debt_noncurrent=0, income_before_extraordinary_items=-20, operating_cash_flow=-30)
    previous["long_term_debt_noncurrent"] = 0
    result = annual_beneish(current, previous)
    assert result["calculation_ready"] and result["ratios"]["TATA"] == pytest.approx(0.1)
    for side in ("current", "previous"):
        changed = deepcopy((current, previous))
        changed[0 if side == "current" else 1]["long_term_debt_noncurrent"] = -1
        assert_invalid(annual_beneish(*changed))


@pytest.mark.parametrize("side", ["current", "previous"])
@pytest.mark.parametrize("changes,domain", [
    ({"cost_of_goods_sold": 100}, "gross_margin"), ({"cost_of_goods_sold": 101}, "gross_margin"),
    ({"current_assets": 60}, "residual_asset_share"), ({"current_assets": 61}, "residual_asset_share"),
])
def test_both_periods_need_positive_gross_margin_and_residual_share(side, changes, domain):
    current, previous = pair()
    {"current": current, "previous": previous}[side].update(changes)
    result = annual_beneish(current, previous)
    assert_invalid(result)
    assert f"nonpositive:{side}.{domain}" in result["reasons"]


@pytest.mark.parametrize("side", ["current", "previous"])
@pytest.mark.parametrize("cast,ppe", [(str, "0.7"), (Decimal, "0.7"), (float, "0.7"),
                                     (str, "0.7000000000000000000000000000001")])
def test_exact_zero_or_negative_residual_cannot_round_into_positive_domain(side, cast, ppe):
    current, previous = pair()
    {"current": current, "previous": previous}[side].update(
        current_assets=cast("0.1"), net_ppe=cast(ppe), total_assets=cast("0.8"),
    )
    result = annual_beneish(current, previous)
    assert_invalid(result)
    assert f"nonpositive:{side}.residual_asset_share" in result["reasons"]


@pytest.mark.parametrize("field", ["entity_id", "currency", "reporting_scope", "accounting_basis", "unit_scale"])
def test_pair_metadata_cannot_mismatch(field):
    current, previous = pair()
    current[field] = 1000 if field == "unit_scale" else "different"
    result = annual_beneish(current, previous)
    assert_invalid(result)
    assert f"metadata_mismatch:{field}" in result["reasons"]


def test_scale_precision_is_not_silently_rounded_into_equality():
    current, previous = pair()
    current["unit_scale"] = "1.00000000000000000000001"
    result = annual_beneish(current, previous)
    assert_invalid(result)
    assert "metadata_mismatch:unit_scale" in result["reasons"]


@pytest.mark.parametrize("value", ["2021.000000000000000000001", Decimal("2021.000000000000000000001")])
def test_fractional_year_is_not_silently_rounded_into_an_integer(value):
    current, previous = pair()
    result = annual_beneish(current | {"fiscal_year": value}, previous)
    assert_invalid(result)
    assert "invalid_fiscal_year:current" in result["reasons"]


def test_extreme_zero_exponent_string_is_rejected_without_decimal_parser_exception():
    current, previous = pair()
    result = annual_beneish(current | {"income_before_extraordinary_items": "0e-9999999999999999999999999"}, previous)
    assert_invalid(result)
    assert "invalid_numeric:current.income_before_extraordinary_items" in result["reasons"]


@pytest.mark.parametrize("side", ["current", "previous"])
@pytest.mark.parametrize("field", ["entity_id", "currency", "unit_scale", "reporting_scope", "accounting_basis",
                                   "period_type", "flow_basis", "fiscal_year", "period_start", "period_end",
                                   "field_statuses"])
def test_required_metadata_cannot_be_missing(side, field):
    current, previous = pair()
    del {"current": current, "previous": previous}[side][field]
    assert_invalid(annual_beneish(current, previous))


@pytest.mark.parametrize("change", [
    {"period_type": "quarterly"}, {"flow_basis": "ttm"}, {"flow_basis": "ytd"},
    {"period_start": "20210101"}, {"period_end": "2021-02-29"}, {"period_end": date(2021, 12, 31)},
    {"period_end": "2020-12-31"}, {"period_start": "2021-12-31"},
    {"period_start": "2020-12-31"}, {"period_start": "2021-01-02"},
    {"fiscal_year": 2020}, {"fiscal_year": 2022}, {"fiscal_year": 2021.5},
    {"fiscal_year": 0}, {"fiscal_year": 10000}, {"unit_scale": 0}, {"unit_scale": -1},
    {"currency": " "}, {"accounting_basis": None}, {"field_statuses": "verified_exact"},
])
def test_mixed_basis_unknown_or_discontinuous_periods_and_invalid_metadata(change):
    current, previous = pair()
    assert_invalid(annual_beneish(current | change, previous, reference_screen=True))


@pytest.mark.parametrize("days", [330, 400])
def test_inclusive_duration_and_end_spacing_boundaries_are_allowed(days):
    current, previous = pair()
    previous_end = date(2020, 12, 31)
    previous.update(period_start=(previous_end - timedelta(days=days - 1)).isoformat())
    current.update(period_start="2021-01-01", period_end=(previous_end + timedelta(days=days)).isoformat())
    assert annual_beneish(current, previous)["calculation_ready"]


@pytest.mark.parametrize("side", ["current", "previous"])
@pytest.mark.parametrize("days", [329, 401])
def test_annual_duration_boundary_rejections(side, days):
    current, previous = pair()
    row = {"current": current, "previous": previous}[side]
    end = date.fromisoformat(row["period_end"])
    row["period_start"] = (end - timedelta(days=days - 1)).isoformat()
    result = annual_beneish(current, previous)
    assert_invalid(result)
    assert f"invalid_annual_duration:{side}" in result["reasons"]


@pytest.mark.parametrize("changes,reason", [
    ({"current_liabilities": 1e308, "long_term_debt_noncurrent": 1e308}, "nonfinite_intermediate:current.leverage_sum"),
    ({"depreciation": 1.7e308, "net_ppe": 1e307, "total_assets": 1.7e308}, "nonfinite_intermediate:current.depreciable_base"),
    ({"income_before_extraordinary_items": 1e308, "operating_cash_flow": -1e308}, "nonfinite_intermediate:current.accruals"),
    ({"income_before_extraordinary_items": 1e308}, "nonfinite:m_score"),
    ({"current_assets": 1e308, "net_ppe": 1e308}, "nonfinite_intermediate:current.asset_sum"),
    ({"trade_receivables_net": 1e308}, "nonfinite_intermediate:DSRI"),
    ({"trade_receivables_net": 5e-324, "sales": 1e308}, "underflow_intermediate:current.DSRI"),
])
def test_intermediate_and_final_overflow_underflow_are_not_clipped(changes, reason):
    current, previous = pair()
    if reason == "nonfinite:m_score":
        current["total_assets"] = 1
        current["current_assets"] = current["net_ppe"] = 0.1
    if reason == "nonfinite_intermediate:DSRI":
        previous["trade_receivables_net"] = 1e-308
    result = annual_beneish(current | changes, previous, reference_screen=True)
    assert_invalid(result)
    assert reason in result["reasons"]


@pytest.mark.parametrize("current,previous", [(None, annual(2020)), (annual(), None), ([], {}), ({}, [])])
def test_invalid_record_mappings(current, previous):
    assert_invalid(annual_beneish(current, previous))


@pytest.mark.parametrize("value", [None, 1, "true", np.bool_(True)])
def test_reference_screen_requires_explicit_boolean(value):
    assert_invalid(annual_beneish(*pair(), reference_screen=value))


def test_reference_threshold_is_strict_even_at_equality(monkeypatch):
    # Inject only the arithmetic boundary to avoid encoding floating roundoff
    # in a back-solved synthetic financial statement.
    target = "systematic_alpha_lab.factor_research.beneish_standard.beneish_m_score"
    for score, flag in ((-1.78, False), (-1.78 - 1e-12, False), (-1.78 + 1e-12, True)):
        monkeypatch.setattr(target, lambda ratios, score=score: {"m_score": score,
                            "calculation_ready": True, "reasons": []})
        assert annual_beneish(*pair(), reference_screen=True)["flag"] is flag


def test_invalid_call_does_not_mutate_inputs():
    current, previous = pair()
    current["field_statuses"]["depreciation"] = "da_proxy"
    original = deepcopy((current, previous))
    assert_invalid(annual_beneish(current, previous))
    assert (current, previous) == original
