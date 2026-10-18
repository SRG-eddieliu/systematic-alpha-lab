import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.factor_research.financial_quality import quarterly_accrual_diagnostic


def statements(asset="company-a"):
    return pd.DataFrame({
        "asset": asset,
        "fiscal_year": [2020] * 4 + [2021] * 4,
        "fiscal_quarter": [1, 2, 3, 4] * 2,
        "period_end": pd.date_range("2020-03-31", periods=8, freq=pd.offsets.QuarterEnd()),
        "currency": "USD", "unit": "millions",
        "net_income": 10.0,
        "operating_cash_flow_ytd": [6., 14., 24., 36., 5., 12., 21., 32.],
        "total_assets": np.arange(100., 180., 10.),
    })


def test_accounting_identity_and_fiscal_year_reset():
    result = quarterly_accrual_diagnostic(statements())
    np.testing.assert_allclose(result.operating_cash_flow_quarter, [6, 8, 10, 12, 5, 7, 9, 11])
    assert result.accrual_quality.iloc[:4].isna().all()
    assert result.ttm_operating_cash_flow.iloc[4] == 35
    assert result.average_assets.iloc[4] == 120
    assert result.accrual_quality.iloc[4] == pytest.approx(-5 / 120)
    assert result.accrual_quality.iloc[7] == pytest.approx(-8 / 150)
    assert result.calculation_ready.tolist() == [False] * 4 + [True] * 4
    assert result.timing_status.eq("snapshot_only_availability_unverified").all()
    assert "available_at" not in result


def test_missing_quarter_cannot_be_treated_as_one_quarter_flow():
    result = quarterly_accrual_diagnostic(statements().drop(index=1))
    q3 = result.query("fiscal_year == 2020 and fiscal_quarter == 3").iloc[0]
    assert pd.isna(q3.operating_cash_flow_quarter)
    assert result.accrual_quality.iloc[:-2].isna().all()
    # The fifth consecutive row after the gap is usable again.
    assert result.calculation_ready.iloc[-2:].all()


def test_partial_first_year_and_negative_cash_flow():
    frame = statements().iloc[2:].copy()
    frame.loc[4, "operating_cash_flow_ytd"] = -5
    result = quarterly_accrual_diagnostic(frame)
    assert pd.isna(result.operating_cash_flow_quarter.iloc[0])
    assert result.operating_cash_flow_quarter.iloc[2] == -5


def test_asset_isolation_sorting_and_input_immutability():
    first = statements()
    other = statements("company-b")
    other["operating_cash_flow_ytd"] *= 2
    combined = pd.concat([first, other]).sample(frac=1, random_state=5)
    before = combined.copy(deep=True)
    result = quarterly_accrual_diagnostic(combined)
    pd.testing.assert_frame_equal(before, combined)
    expected = quarterly_accrual_diagnostic(first)
    pd.testing.assert_frame_equal(result.query("asset == 'company-a'").reset_index(drop=True), expected)
    assert result.query("asset == 'company-b'").accrual_quality.iloc[-1] != expected.accrual_quality.iloc[-1]


def test_future_mutation_cannot_change_earlier_diagnostic():
    frame = statements()
    before = quarterly_accrual_diagnostic(frame)
    frame.loc[7, ["net_income", "operating_cash_flow_ytd", "total_assets"]] = 9999
    pd.testing.assert_frame_equal(before.iloc[:7], quarterly_accrual_diagnostic(frame).iloc[:7])


def test_noncalendar_fiscal_quarters_use_fiscal_labels():
    frame = statements()
    frame["period_end"] -= pd.DateOffset(months=2)
    result = quarterly_accrual_diagnostic(frame)
    assert result.operating_cash_flow_quarter.iloc[4] == 5
    assert result.accrual_quality.iloc[4] == pytest.approx(-5 / 120)


@pytest.mark.parametrize("column", ["net_income", "operating_cash_flow_ytd", "total_assets"])
def test_missing_amounts_are_not_imputed(column):
    frame = statements()
    frame.loc[4, column] = np.nan
    result = quarterly_accrual_diagnostic(frame)
    assert not result.calculation_ready.iloc[4]


@pytest.mark.parametrize("amount", [0, -1])
def test_nonpositive_endpoint_assets_block_ratio(amount):
    frame = statements()
    frame.loc[0, "total_assets"] = amount
    assert not quarterly_accrual_diagnostic(frame).calculation_ready.iloc[4]


@pytest.mark.parametrize("issue", [
    "missing_field", "duplicate", "duplicate_date", "quarter", "fractional_year",
    "null_year", "null_asset", "blank_currency", "mixed_currency", "mixed_unit",
    "infinite", "missing_date", "bad_date_order",
])
def test_ambiguous_or_invalid_contract_rejected(issue):
    frame = statements()
    if issue == "missing_field": frame = frame.drop(columns="unit")
    if issue == "duplicate": frame = pd.concat([frame, frame.iloc[:1]])
    if issue == "duplicate_date": frame.loc[1, "period_end"] = frame.loc[0, "period_end"]
    if issue == "quarter": frame.loc[0, "fiscal_quarter"] = 5
    if issue == "fractional_year": frame = frame.assign(fiscal_year=2020.5)
    if issue == "null_year": frame.loc[0, "fiscal_year"] = np.nan
    if issue == "null_asset": frame.loc[0, "asset"] = None
    if issue == "blank_currency": frame.loc[0, "currency"] = " "
    if issue == "mixed_currency": frame.loc[0, "currency"] = "CAD"
    if issue == "mixed_unit": frame.loc[0, "unit"] = "thousands"
    if issue == "infinite": frame.loc[0, "net_income"] = np.inf
    if issue == "missing_date": frame.loc[0, "period_end"] = pd.NaT
    if issue == "bad_date_order": frame.loc[0, "period_end"] = frame.loc[2, "period_end"] + pd.Timedelta(days=1)
    with pytest.raises(ValueError):
        quarterly_accrual_diagnostic(frame)


def test_empty_input_has_stable_output_contract():
    result = quarterly_accrual_diagnostic(statements().iloc[:0])
    assert result.empty
    assert {"accrual_quality", "operating_cash_flow_quarter", "timing_status"}.issubset(result.columns)
