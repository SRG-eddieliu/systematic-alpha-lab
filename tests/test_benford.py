from decimal import Decimal, localcontext

import numpy as np
import pandas as pd
import pytest
from scipy.stats import chisquare

from systematic_alpha_lab.factor_research.factors.benford import (
    BenfordChiSquareD1, BenfordChiSquareD2,
    _benford_expected_first, _benford_expected_second, _chi_square,
    _compute_benford_scores, _first_second_digits,
    benford_asof_diagnostics, benford_snapshot_diagnostics,
)


def snapshot(values=(12, 23, 34), asset="a", period="2020-03-31"):
    return pd.DataFrame({"asset": asset, "period_end": period,
                         "field": [f"amount-{i}" for i in range(len(values))], "value": list(values)})


def filings():
    records = []
    for asset, period, release, values in [
        ("a", "2020-03-31", "2020-05-01T21:00Z", [12, 23]),
        ("a", "2020-06-30", "2020-08-01T21:00Z", [34, 45]),
        ("a", "2020-03-31", "2020-09-01T21:00Z", [98, 87]),
        ("b", "2020-03-31", "2020-05-01T21:00Z", [56, 67]),
    ]:
        frame = snapshot(values, asset, period).assign(available_at=release, currency="USD", unit="millions")
        records.append(frame)
    return pd.concat(records, ignore_index=True)


def decisions():
    return pd.DataFrame({"asset": ["a", "a", "a", "b", "c"], "decision_at": [
        "2020-05-01T20:59Z", "2020-05-01T21:00Z", "2020-09-02T13:30Z",
        "2020-05-04T13:30Z", "2020-05-04T13:30Z",
    ]})


FIELDS = ["amount-0", "amount-1"]


def test_digit_distributions_have_correct_marginals():
    first, second = _benford_expected_first(), _benford_expected_second()
    assert first.sum() == pytest.approx(1, abs=1e-14)
    assert second.sum() == pytest.approx(1, abs=1e-14)
    assert second[0] == pytest.approx(0.11967926859688073)
    assert second[9] == pytest.approx(0.08499735205755076)
    # Independent construction from the 90 joint first-two-digit bins.
    joint = np.log10(np.arange(11, 101) / np.arange(10, 100)).reshape(9, 10)
    np.testing.assert_allclose(joint.sum(axis=0), second, rtol=0, atol=1e-15)
    np.testing.assert_allclose(joint.sum(axis=1), first, rtol=0, atol=1e-15)


def test_fractional_negative_scientific_and_extreme_magnitudes():
    values = pd.Series(["0.000310", Decimal("-9.87e-100"), "10000000", "3e300", 5e-324,
                        "1.23e309", 0, -0.0, None, np.nan, np.inf, -np.inf, True, "bad"],
                       index=list(range(10, 24)))
    first, second = _first_second_digits(values)
    assert first.tolist() == [3, 9, 1, 3, 5, 1]
    assert second.tolist() == [1, 8, 0, 0, 0, 2]
    assert first.index.tolist() == list(range(10, 16))


def test_decimal_extraction_does_not_round_with_context():
    value = Decimal("-9.9999999999999999999999999999999999999e999999")
    with localcontext() as context:
        context.prec = 2
        first, second = _first_second_digits(pd.Series([value]))
    assert first.tolist() == [9]
    assert second.tolist() == [9]


def test_single_digit_values_have_implicit_second_digit_zero():
    first, second = _first_second_digits(pd.Series([9, 9.0, "9e3", "0.009", "9.000"]))
    assert first.tolist() == [9] * 5
    assert second.tolist() == [0] * 5


def test_sign_and_power_of_ten_scaling_leave_digits_unchanged():
    values = pd.Series(["-0.003104", "987.65", "10", "8e-300"])
    scaled = pd.Series(["-3104", "987650000", "10000000", "8e-294"])
    for left, right in zip(_first_second_digits(values), _first_second_digits(scaled)):
        pd.testing.assert_series_equal(left, right)


def test_pearson_statistic_matches_scipy_and_uses_counts():
    counts = np.array([31, 18, 13, 10, 8, 7, 5, 4, 4])
    expected = _benford_expected_first()
    assert _chi_square(counts, expected) == pytest.approx(chisquare(counts, expected * counts.sum()).statistic)
    assert _chi_square(counts * 2, expected) == pytest.approx(2 * _chi_square(counts, expected))
    assert np.isnan(_chi_square(np.zeros(9), expected))


@pytest.mark.parametrize("counts,probs", [
    ([1, 2], [0.3, 0.3]), ([1, 2], [1, 0]), ([-1, 2], [0.5, 0.5]),
    ([0.5, 2], [0.5, 0.5]), ([np.inf, 2], [0.5, 0.5]), ([1], [0.5, 0.5]),
    ([], []), ([[1, 2]], [[0.5, 0.5]]), ([1, 2], [np.nan, 0.5]),
])
def test_bad_count_or_probability_vectors_rejected(counts, probs):
    with pytest.raises(ValueError):
        _chi_square(counts, probs)


def test_snapshot_exclusions_counts_and_small_sample_screen():
    result = benford_snapshot_diagnostics(snapshot([12, -23, "0.034", 7, 0, None, np.inf, "bad"]))
    row = result.iloc[0]
    assert (row.n_values, row.n_nonzero, row.n_zero, row.n_invalid, row.n_negative) == (8, 4, 1, 3, 1)
    assert not row.cell_count_screen_d1 and not row.cell_count_screen_d2
    assert row.min_expected_d1 < 5 and row.min_expected_d2 < 5
    assert row.timing_status == "snapshot_only_availability_unverified"
    assert "available_at" not in result and "p_value" not in result


def test_cell_count_screen_is_only_an_observed_and_expected_count_check():
    result = benford_snapshot_diagnostics(snapshot(list(range(10, 100)) * 10)).iloc[0]
    assert result.cell_count_screen_d1 and result.cell_count_screen_d2
    assert not any("p_value" in name or "probability" in name for name in result.index)


def test_empty_or_all_excluded_inputs_preserve_missing_score():
    assert benford_snapshot_diagnostics(snapshot([])).empty
    row = benford_snapshot_diagnostics(snapshot([0, None, "inf"])).iloc[0]
    assert row.n_nonzero == 0 and np.isnan(row.chi2_d1) and np.isnan(row.chi2_d2)
    legacy = snapshot([]).rename(columns={"asset": "ticker", "period_end": "fiscalDateEnding"})
    assert all(panel.empty for panel in _compute_benford_scores(legacy))


def test_snapshot_company_isolation_ordering_and_input_preservation():
    first = snapshot([12, 23])
    combined = pd.concat([first, snapshot([98, 87], "b")]).sample(frac=1, random_state=7)
    original = combined.copy(deep=True)
    result = benford_snapshot_diagnostics(combined)
    pd.testing.assert_frame_equal(combined, original)
    pd.testing.assert_frame_equal(result.query("asset == 'a'").reset_index(drop=True),
                                  benford_snapshot_diagnostics(first))


@pytest.mark.parametrize("issue", ["missing_field", "duplicate_field", "null_asset", "null_period", "blank_field"])
def test_ambiguous_snapshot_contract_rejected(issue):
    frame = snapshot()
    if issue == "missing_field": frame = frame.drop(columns="field")
    if issue == "duplicate_field": frame = pd.concat([frame, frame.iloc[:1]])
    if issue == "null_asset": frame.loc[0, "asset"] = None
    if issue == "null_period": frame.loc[0, "period_end"] = ""
    if issue == "blank_field": frame.loc[0, "field"] = " "
    with pytest.raises(ValueError):
        benford_snapshot_diagnostics(frame)


def test_asof_release_boundary_newest_period_and_asset_isolation():
    result = benford_asof_diagnostics(filings(), decisions(), fields=FIELDS)
    assert result.chi2_d1.iloc[[0, 4]].isna().all()
    assert result.period_end.iloc[1] == pd.Timestamp("2020-03-31T00:00Z")
    assert result.period_end.iloc[2] == pd.Timestamp("2020-06-30T00:00Z")
    expected = benford_snapshot_diagnostics(snapshot([34, 45])).iloc[0]
    assert result.chi2_d2.iloc[2] == pytest.approx(expected.chi2_d2)
    assert result.chi2_d1.iloc[3] != result.chi2_d1.iloc[1]
    assert result.available_at.iloc[1] == result.decision_at.iloc[1]
    assert result.timing_status.iloc[0] == "no_complete_available_period"


def test_latest_field_revision_uses_only_published_versions():
    frame = filings().query("asset == 'a' and period_end == '2020-03-31'").copy()
    # Only amount-0 is revised; amount-1 retains its previously published value.
    frame = frame.drop(index=5)
    result = benford_asof_diagnostics(frame, decisions().iloc[1:3], fields=FIELDS)
    original = benford_snapshot_diagnostics(snapshot([12, 23])).iloc[0]
    revised = benford_snapshot_diagnostics(snapshot([98, 23])).iloc[0]
    assert result.chi2_d1.iloc[0] == pytest.approx(original.chi2_d1)
    assert result.chi2_d1.iloc[1] == pytest.approx(revised.chi2_d1)


def test_incomplete_new_period_waits_for_entire_declared_field_set():
    frame = filings()
    frame.loc[3, "available_at"] = "2020-10-01T21:00Z"
    result = benford_asof_diagnostics(frame, decisions().iloc[2:3], fields=FIELDS)
    assert result.period_end.iloc[0] == pd.Timestamp("2020-03-31T00:00Z")
    # Without any earlier complete period, the result stays missing.
    result = benford_asof_diagnostics(frame.iloc[2:4], decisions().iloc[2:3], fields=FIELDS)
    assert result.chi2_d1.isna().all()


def test_published_missing_revision_does_not_restore_superseded_value():
    frame = filings().query("asset == 'a' and period_end == '2020-03-31'").copy()
    frame.loc[frame.available_at.str.startswith("2020-09"), "value"] = np.nan
    result = benford_asof_diagnostics(frame, decisions().iloc[2:3], fields=FIELDS)
    assert result.n_nonzero.iloc[0] == 0
    assert result.chi2_d1.isna().all()


def test_future_filings_and_revisions_cannot_change_earlier_results():
    frame, decision = filings(), decisions().iloc[:2]
    original = frame.copy(deep=True)
    before = benford_asof_diagnostics(frame, decision, fields=FIELDS)
    pd.testing.assert_frame_equal(original, frame)
    frame.loc[frame.available_at.str.startswith(("2020-08", "2020-09")), "value"] = 99
    pd.testing.assert_frame_equal(before, benford_asof_diagnostics(frame, decision, fields=FIELDS))


def test_timezone_conversion_and_shuffled_inputs():
    frame = filings().sample(frac=1, random_state=3)
    decision = pd.DataFrame({"asset": ["a"], "decision_at": ["2020-05-01T17:00:00-04:00"]})
    result = benford_asof_diagnostics(frame, decision, fields=FIELDS)
    assert result.available_at.iloc[0] == result.decision_at.iloc[0]
    assert result.decision_at.iloc[0] == pd.Timestamp("2020-05-01T21:00Z")


@pytest.mark.parametrize("issue", [
    "missing_release", "naive_release", "missing_time", "duplicate_version", "early_release",
    "naive_decision", "null_decision", "mixed_currency", "mixed_unit", "unexpected_field", "blank_unit",
])
def test_invalid_asof_metadata_rejected(issue):
    frame, decision = filings(), decisions()
    if issue == "missing_release": frame = frame.drop(columns="available_at")
    if issue == "naive_release": frame.loc[0, "available_at"] = "2020-05-01"
    if issue == "missing_time": frame.loc[0, "available_at"] = ""
    if issue == "duplicate_version": frame = pd.concat([frame, frame.iloc[:1]])
    if issue == "early_release": frame.loc[0, "available_at"] = "2020-03-01T21:00Z"
    if issue == "naive_decision": decision.loc[0, "decision_at"] = "2020-05-01"
    if issue == "null_decision": decision.loc[0, "decision_at"] = None
    if issue == "mixed_currency": frame.loc[0, "currency"] = "CAD"
    if issue == "mixed_unit": frame.loc[0, "unit"] = "thousands"
    if issue == "unexpected_field": frame.loc[0, "field"] = "identifier"
    if issue == "blank_unit": frame.loc[0, "unit"] = " "
    with pytest.raises(ValueError):
        benford_asof_diagnostics(frame, decision, fields=FIELDS)


@pytest.mark.parametrize("fields", [[], ["amount-0", "amount-0"], [""], "amount-0", [None]])
def test_explicit_unique_field_set_required(fields):
    with pytest.raises(ValueError):
        benford_asof_diagnostics(filings(), decisions(), fields=fields)


def test_empty_filings_and_decisions():
    frame, decision = filings(), decisions()
    assert benford_asof_diagnostics(frame, decision.iloc[:0], fields=FIELDS).empty
    result = benford_asof_diagnostics(frame.iloc[:0], decision, fields=FIELDS)
    assert len(result) == len(decision) and result.chi2_d1.isna().all()


class Loader:
    def __init__(self):
        common = {"ticker": ["a", "a"], "fiscalDateEnding": ["2020-03-31", "2019-12-31"],
                  "period_type": ["quarterly", "annual"]}
        self.frames = {
            "fundamentals_income_statement": pd.DataFrame({**common, "netIncome": ["0.034", 99]}),
            "fundamentals_balance_sheet": pd.DataFrame({**common, "totalAssets": ["-1200", 88]}),
        }

    def load_long(self, dataset):
        return self.frames[dataset]

    def load_price_wide(self, **kwargs):
        raise AssertionError("Snapshot diagnostics must not project onto price dates")


@pytest.mark.parametrize("factor_class", [BenfordChiSquareD1, BenfordChiSquareD2])
def test_legacy_snapshot_is_explicit_and_does_not_mutate_source(factor_class):
    loader = Loader()
    before = {key: value.copy(deep=True) for key, value in loader.frames.items()}
    result = factor_class().compute_snapshot(loader)
    assert result.shape == (1, 1)
    for key in before:
        pd.testing.assert_frame_equal(before[key], loader.frames[key])


@pytest.mark.parametrize("factor_class", [BenfordChiSquareD1, BenfordChiSquareD2])
def test_legacy_daily_projection_cannot_silently_use_period_end(factor_class):
    factor = factor_class()
    with pytest.raises(ValueError, match="available_at"):
        factor.compute_raw_factor(object())
    with pytest.raises(ValueError, match="available_at"):
        factor.compute(object())
    with pytest.raises(ValueError, match="publication-time"):
        factor.post_process(pd.DataFrame({"a": [1.0]}))


def test_legacy_snapshot_rejects_duplicate_quarters():
    loader = Loader()
    key = "fundamentals_income_statement"
    loader.frames[key] = pd.concat([loader.frames[key], loader.frames[key].iloc[:1]])
    with pytest.raises(ValueError, match="duplicate quarter"):
        BenfordChiSquareD1().compute_snapshot(loader)


def test_legacy_snapshot_requires_explicit_period_type():
    loader = Loader()
    key = "fundamentals_income_statement"
    loader.frames[key] = loader.frames[key].drop(columns="period_type")
    with pytest.raises(ValueError, match="period_type"):
        BenfordChiSquareD1().compute_snapshot(loader)
