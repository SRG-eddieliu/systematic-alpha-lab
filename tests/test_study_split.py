"""Synthetic timestamp contracts; no historical market data or model fitting."""

import hashlib

import pandas as pd
import pytest

from systematic_alpha_lab.factor_research.study_split import TIMES, monthly_chronological_split

HASHES = {"synthetic_fixture": hashlib.sha256(b"synthetic study fixture v1").hexdigest()}


def observations(months=10):
    records = []
    for decision in pd.date_range("2020-01-01", periods=months, freq="MS", tz="UTC") + pd.Timedelta(days=20, hours=20):
        for asset in ("synthetic:A", "synthetic:B"):
            records.append(
                {
                    "asset_id": asset,
                    "feature_available_at": decision - pd.Timedelta(days=1),
                    "decision_at": decision,
                    "holding_start_at": decision + pd.Timedelta(days=1),
                    "holding_end_at": decision + pd.Timedelta(days=35),
                    "label_available_at": decision + pd.Timedelta(days=35, hours=2),
                }
            )
    return pd.DataFrame(records)


def test_month_counts_and_overlapping_label_windows_are_hand_calculated():
    result, manifest = monthly_chronological_split(observations(), source_hashes=HASHES)
    assert [manifest["segments"][name]["assigned_months"] for name in ("development", "validation", "test")] == [
        6,
        2,
        2,
    ]
    assert [manifest["segments"][name]["retained_rows"] for name in ("development", "validation", "test")] == [10, 2, 4]
    assert result.loc[result.purged, "decision_month"].tolist() == ["2020-06"] * 2 + ["2020-08"] * 2
    for segment, next_segment in (("development", "validation"), ("validation", "test")):
        retained = result.loc[result.assigned_split.eq(segment) & ~result.purged]
        next_decision = result.loc[result.assigned_split.eq(next_segment), "decision_at"].min()
        assert retained.label_available_at.lt(next_decision).all()


def test_label_publication_delay_can_purge_a_finished_holding_period():
    data = observations()
    boundary = data.decision_at.iloc[12]
    assert data.holding_end_at.iloc[8] < boundary
    data.loc[8, "label_available_at"] = boundary + pd.Timedelta(minutes=1)
    result, _ = monthly_chronological_split(data, source_hashes=HASHES)
    assert result.purged.iloc[8]


def test_label_available_exactly_at_next_decision_is_purged():
    data = observations()
    data.loc[10, "holding_end_at"] = data.decision_at.iloc[10] + pd.Timedelta(days=2)
    data.loc[10, "label_available_at"] = data.decision_at.iloc[12]
    result, _ = monthly_chronological_split(data, source_hashes=HASHES)
    assert result.purged.iloc[10]


def test_asset_count_cannot_shift_the_calendar_boundaries():
    data = observations()
    _, before = monthly_chronological_split(data, source_hashes=HASHES)
    extra = pd.concat([data.iloc[:1].assign(asset_id=f"synthetic:extra-{i}") for i in range(20)])
    _, after = monthly_chronological_split(pd.concat([data, extra]), source_hashes=HASHES)
    assert before["boundaries"] == after["boundaries"]
    assert before["usable_decision_months"] == after["usable_decision_months"]


def test_return_values_and_row_order_cannot_determine_the_split():
    data = observations().assign(future_return=999.0)
    original = data.copy(deep=True)
    result, manifest = monthly_chronological_split(data, source_hashes=HASHES)
    changed = data.sample(frac=1, random_state=5).copy()
    changed.future_return = -999.0
    second, other_manifest = monthly_chronological_split(changed, source_hashes=HASHES)
    assert manifest == other_manifest
    cols = ["asset_id", "decision_at", "assigned_split", "purged"]
    pd.testing.assert_frame_equal(
        result[cols].sort_values(cols[:2]).reset_index(drop=True),
        second[cols].sort_values(cols[:2]).reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(data, original)
    assert not manifest["model_fitted"] and not manifest["return_values_inspected"]


def test_equivalent_source_timezones_normalize_to_the_same_manifest():
    data = observations()
    _, first = monthly_chronological_split(data, source_hashes=HASHES)
    for name in TIMES:
        data[name] = data[name].dt.tz_convert("America/New_York")
    _, second = monthly_chronological_split(data, source_hashes=HASHES)
    assert first == second


@pytest.mark.parametrize("months,expected", [(5, [3, 1, 1]), (7, [4, 1, 2]), (8, [4, 2, 2])])
def test_rounding_uses_cumulative_month_boundaries(months, expected):
    data = observations(months)
    data.holding_end_at = data.decision_at + pd.Timedelta(days=10)
    data.label_available_at = data.holding_end_at
    _, manifest = monthly_chronological_split(data, source_hashes=HASHES)
    assert [manifest["segments"][name]["assigned_months"] for name in ("development", "validation", "test")] == expected


@pytest.mark.parametrize("months", [1, 2, 3, 4])
def test_short_calendars_are_rejected_even_without_holding_overlap(months):
    data = observations(months)
    data.holding_end_at = data.decision_at + pd.Timedelta(days=10)
    data.label_available_at = data.holding_end_at
    with pytest.raises(ValueError, match="at least five"):
        monthly_chronological_split(data, source_hashes=HASHES)


@pytest.mark.parametrize("name", TIMES)
@pytest.mark.parametrize("value", [None, "2020-01-21 20:00:00"])
def test_missing_or_naive_timestamps_are_not_imputed(name, value):
    data = observations()
    data[name] = data[name].astype(object)
    data.loc[0, name] = value
    with pytest.raises(ValueError, match="timezone-aware"):
        monthly_chronological_split(data, source_hashes=HASHES)


@pytest.mark.parametrize(
    "issue",
    [
        "future_feature",
        "same_execution",
        "reversed_holding",
        "early_label",
        "duplicate",
        "two_decisions",
        "null_asset",
        "short_calendar",
        "empty_after_purge",
        "old_output",
    ],
)
def test_invalid_study_contract_is_rejected(issue):
    data = observations()
    if issue == "future_feature":
        data.loc[0, "feature_available_at"] = data.decision_at.iloc[0] + pd.Timedelta(seconds=1)
    if issue == "same_execution":
        data.loc[0, "holding_start_at"] = data.decision_at.iloc[0]
    if issue == "reversed_holding":
        data.loc[0, "holding_end_at"] = data.decision_at.iloc[0]
    if issue == "early_label":
        data.loc[0, "label_available_at"] = data.holding_start_at.iloc[0]
    if issue == "duplicate":
        data = pd.concat([data, data.iloc[:1]])
    if issue == "two_decisions":
        data.loc[0, "decision_at"] += pd.Timedelta(minutes=1)
    if issue == "null_asset":
        data.loc[0, "asset_id"] = None
    if issue == "short_calendar":
        data = data.iloc[:8]
    if issue == "empty_after_purge":
        data["label_available_at"] = pd.Timestamp("2029-01-01", tz="UTC")
    if issue == "old_output":
        data["assigned_split"] = "test"
    with pytest.raises(ValueError):
        monthly_chronological_split(data, source_hashes=HASHES)


@pytest.mark.parametrize("hashes", [{}, {"source": "not-a-sha"}, {"": "a" * 64}])
def test_source_hashes_are_required_before_freezing_a_plan(hashes):
    with pytest.raises(ValueError, match="SHA-256"):
        monthly_chronological_split(observations(), source_hashes=hashes)
