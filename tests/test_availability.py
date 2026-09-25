import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.factor_research.availability import fundamentals_asof


def inputs():
    filings = pd.DataFrame({
        "asset": ["A", "A", "A", "B"],
        "period_end": ["2020-03-31", "2020-06-30", "2020-03-31", "2020-03-31"],
        "available_at": ["2020-05-01T21:00Z", "2020-08-01T21:00Z", "2020-09-01T21:00Z", "2020-05-01T21:00Z"],
        "value": [1., 2., 99., 7.],
    })
    decisions = pd.DataFrame({"asset": ["A", "A", "A", "B", "C"], "decision_at": [
        "2020-05-01T20:00Z", "2020-05-04T13:30Z", "2020-09-02T13:30Z",
        "2020-05-04T13:30Z", "2020-05-04T13:30Z"]})
    return filings, decisions


def test_availability_restatements_and_asset_isolation():
    f, d = inputs()
    result = fundamentals_asof(f, d)
    np.testing.assert_allclose(result.value, [np.nan, 1, 2, 7, np.nan], equal_nan=True)


def test_future_mutation_cannot_change_past_feature():
    f, d = inputs()
    early = d.iloc[:2]
    before = fundamentals_asof(f, early)
    f.loc[f.available_at.str.startswith("2020-09"), "value"] = -10000
    pd.testing.assert_frame_equal(before, fundamentals_asof(f, early))


def test_restatement_applies_only_after_release_when_period_is_latest():
    f, d = inputs()
    f = f.drop(index=1)
    result = fundamentals_asof(f, d)
    assert result.value.iloc[1] == 1
    assert result.value.iloc[2] == 99


@pytest.mark.parametrize("issue", ["missing", "null", "empty_time", "duplicate", "infinite", "period"])
def test_bad_inputs_rejected(issue):
    f, d = inputs()
    if issue == "missing": f = f.drop(columns="available_at")
    if issue == "null": f.loc[0, "available_at"] = None
    if issue == "empty_time": f.loc[0, "available_at"] = ""
    if issue == "duplicate": f = pd.concat([f, f.iloc[:1]])
    if issue == "infinite": f.loc[0, "value"] = np.inf
    if issue == "period": f.loc[0, "period_end"] = "2030-01-01"
    with pytest.raises(ValueError): fundamentals_asof(f, d)


def test_empty_decisions_and_filings():
    f, d = inputs()
    assert fundamentals_asof(f, d.iloc[:0]).empty
    assert fundamentals_asof(f.iloc[:0], d).value.isna().all()
