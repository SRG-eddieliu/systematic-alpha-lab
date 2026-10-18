"""Quarter-flow arithmetic and provider integration with synthetic inputs only."""
from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline.quarterly_review import review_quarterly_snapshots
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.factor_research.financial_quality import (
    accrual_from_quarterly_flows, quarterly_accrual_diagnostic,
)

NOW = datetime(2022, 2, 1, tzinfo=timezone.utc)


def quarterly_flows(asset="source-a"):
    return pd.DataFrame({
        "asset": asset, "period_end": pd.date_range("2020-03-31", periods=8, freq=pd.offsets.QuarterEnd()),
        "currency": "USD", "unit": "millions", "net_income": 10.,
        "operating_cash_flow_quarter": [6., 8., 10., 12., 5., 7., 9., 11.],
        "total_assets": np.arange(100., 180., 10.),
    })


def sources():
    result = {}
    for function, field, value in [("INCOME_STATEMENT", "netIncome", 10),
                                    ("CASH_FLOW", "operatingCashflow", 8),
                                    ("BALANCE_SHEET", "totalAssets", 100)]:
        annual, quarterly = [], []
        for year in (2020, 2021):
            stock = value + 20 * (year - 2020)
            row = {"fiscalDateEnding": f"{year}-12-31", "reportedCurrency": "USD",
                   field: str(stock if function == "BALANCE_SHEET" else value * 4)}
            if function == "CASH_FLOW": row["netIncome"] = "40"
            annual.append(row)
            for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
                quarter = {**row, "fiscalDateEnding": f"{year}-{month:02d}-{day}",
                           field: str(stock if function == "BALANCE_SHEET" else value)}
                if function == "CASH_FLOW": quarter["netIncome"] = "10"
                quarterly.append(quarter)
        result[function] = {"symbol": "SYNTH", "annualReports": annual, "quarterlyReports": quarterly}
    return result


def capture(store, payloads=None):
    return [store.capture("alpha_vantage", {"function": function, "symbol": "SYNTH"},
                          json.dumps(payload).encode(), observed_at=NOW)
            for function, payload in (payloads or sources()).items()]


def reviewed(store, records):
    manifest = review_quarterly_snapshots(store, records)
    return manifest, pd.read_parquet(store.root / manifest["tables"]["quarterly_review"]["path"])


def test_direct_flows_match_explicit_ytd_conversion_without_redifferencing():
    frame = quarterly_flows()
    direct = accrual_from_quarterly_flows(frame)
    ytd = frame.assign(fiscal_year=[2020] * 4 + [2021] * 4, fiscal_quarter=[1, 2, 3, 4] * 2,
                       operating_cash_flow_ytd=[6., 14., 24., 36., 5., 12., 21., 32.])
    expected = quarterly_accrual_diagnostic(ytd)
    np.testing.assert_allclose(direct.accrual_quality, expected.accrual_quality, equal_nan=True)
    np.testing.assert_allclose(direct.operating_cash_flow_quarter, frame.operating_cash_flow_quarter)
    assert direct.ttm_operating_cash_flow.iloc[4] == 35
    assert direct.average_assets.iloc[4] == 120
    assert direct.accrual_quality.iloc[4] == pytest.approx(-5 / 120)
    assert direct.calculation_ready.tolist() == [False] * 4 + [True] * 4


def test_gaps_require_four_flows_and_five_consecutive_asset_dates():
    result = accrual_from_quarterly_flows(quarterly_flows().drop(index=1))
    assert result.ttm_net_income.iloc[:4].isna().all()
    assert result.calculation_ready.tolist() == [False] * 5 + [True] * 2


@pytest.mark.parametrize("spacing", ["60D", "120D"])
def test_four_short_or_long_intervals_are_not_treated_as_one_year(spacing):
    frame = quarterly_flows().assign(period_end=pd.date_range("2020-01-01", periods=8, freq=spacing))
    assert not accrual_from_quarterly_flows(frame).calculation_ready.any()


def test_asset_isolation_sorting_immutability_and_future_mutation():
    first = quarterly_flows()
    other = quarterly_flows("source-b").assign(operating_cash_flow_quarter=20.)
    combined = pd.concat([first, other]).sample(frac=1, random_state=1)
    original = combined.copy(deep=True)
    result = accrual_from_quarterly_flows(combined)
    pd.testing.assert_frame_equal(combined, original)
    expected = accrual_from_quarterly_flows(first)
    pd.testing.assert_frame_equal(result.loc[result.asset.eq("source-a")].reset_index(drop=True), expected)
    first.loc[7, ["net_income", "operating_cash_flow_quarter", "total_assets"]] = 9999
    pd.testing.assert_frame_equal(accrual_from_quarterly_flows(first).iloc[:7], expected.iloc[:7])


@pytest.mark.parametrize("column", ["currency", "unit"])
def test_metadata_change_blocks_windows_until_five_consistent_rows(column):
    frame = quarterly_flows()
    frame.loc[3:, column] = "CAD" if column == "currency" else "thousands"
    result = accrual_from_quarterly_flows(frame)
    assert result.calculation_ready.tolist() == [False] * 7 + [True]


@pytest.mark.parametrize("column", ["net_income", "operating_cash_flow_quarter", "total_assets"])
def test_missing_amount_does_not_get_imputed(column):
    frame = quarterly_flows()
    frame.loc[4, column] = np.nan
    assert not accrual_from_quarterly_flows(frame).calculation_ready.iloc[4]


@pytest.mark.parametrize("issue", ["duplicate", "missing_date", "blank_id", "infinite", "missing_field"])
def test_invalid_core_contract_is_rejected(issue):
    frame = quarterly_flows()
    if issue == "duplicate": frame = pd.concat([frame, frame.iloc[:1]])
    if issue == "missing_date": frame.loc[0, "period_end"] = pd.NaT
    if issue == "blank_id": frame.loc[0, "asset"] = " "
    if issue == "infinite": frame.loc[0, "net_income"] = np.inf
    if issue == "missing_field": frame = frame.drop(columns="unit")
    with pytest.raises(ValueError): accrual_from_quarterly_flows(frame)


def test_empty_input_and_noncalendar_periods():
    empty = accrual_from_quarterly_flows(quarterly_flows().iloc[:0])
    assert empty.empty and "accrual_quality" in empty
    original = quarterly_flows()
    shifted = original.assign(period_end=original.period_end - pd.DateOffset(months=2))
    np.testing.assert_allclose(accrual_from_quarterly_flows(original).accrual_quality,
                               accrual_from_quarterly_flows(shifted).accrual_quality, equal_nan=True)


def test_provider_quarters_produce_ttm_and_preserve_unknown_source_contracts(tmp_path):
    store = SnapshotStore(tmp_path)
    records = capture(store)
    manifest, frame = reviewed(store, records)
    assert len(frame) == 8 and frame.calculation_ready.sum() == 4
    assert frame.accrual_quality.iloc[-1] == pytest.approx(-8 / 110)
    assert frame.ttm_operating_cash_flow.iloc[-1] == 32
    assert frame.ttm_source_income_comparable_quarters.iloc[-1] == 4
    assert frame.ttm_source_income_difference_count.iloc[-1] == 0
    assert frame.available_at.isna().all() and frame.cash_flow_basis.str.endswith("unverified").all()
    assert frame.identifier_basis.eq("provider_symbol_unmapped").all()
    assert not {"fiscal_year", "fiscal_quarter"}.intersection(frame.columns)
    assert review_quarterly_snapshots(store, records) == manifest


def test_quarter_and_annual_source_differences_remain_visible(tmp_path):
    store = SnapshotStore(tmp_path)
    payloads = sources()
    payloads["CASH_FLOW"]["quarterlyReports"][-1]["netIncome"] = "9"
    payloads["CASH_FLOW"]["quarterlyReports"][-1]["operatingCashflow"] = "9"
    _, frame = reviewed(store, capture(store, payloads))
    assert frame.ttm_source_income_difference_count.iloc[-1] == 1
    assert frame.source_income_difference_text.iloc[-1] == "1"
    assert frame.cash_flow_annual_check.iloc[-1] == "value_difference"
    assert frame.ttm_operating_cash_flow.iloc[-1] == 33


@pytest.mark.parametrize("issue", ["missing_quarter", "missing_amount", "currency"])
def test_bad_provider_quarter_cannot_be_restored_from_annuals(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    payloads = sources()
    row = payloads["CASH_FLOW"]["quarterlyReports"][4]
    if issue == "missing_quarter": payloads["CASH_FLOW"]["quarterlyReports"].pop(4)
    if issue == "missing_amount": row["operatingCashflow"] = "None"
    if issue == "currency": row["reportedCurrency"] = "CAD"
    _, frame = reviewed(store, capture(store, payloads))
    assert len(frame) == 8 and not frame.calculation_ready.iloc[4:].any()
    assert frame.available_at.isna().all()


def test_extra_unmatched_source_date_does_not_displace_a_comparison_quarter(tmp_path):
    store = SnapshotStore(tmp_path)
    payloads = sources()
    payloads["CASH_FLOW"]["quarterlyReports"][4]["netIncome"] = "9"
    extra = {**payloads["CASH_FLOW"]["quarterlyReports"][-1], "fiscalDateEnding": "2021-12-30"}
    payloads["CASH_FLOW"]["quarterlyReports"].append(extra)
    _, frame = reviewed(store, capture(store, payloads))
    assert len(frame) == 9
    assert frame.ttm_source_income_comparable_quarters.iloc[-1] == 4
    assert frame.ttm_source_income_difference_count.iloc[-1] == 1
    assert frame.accrual_quality.iloc[-1] == pytest.approx(-8 / 110)


@pytest.mark.parametrize("issue", ["raw", "derived"])
def test_cached_quarterly_review_checks_dependency_integrity(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    records = capture(store)
    manifest, frame = reviewed(store, records)
    path = records[0]["raw_path"] if issue == "raw" else manifest["tables"]["quarterly_review"]["path"]
    (store.root / path).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash"):
        review_quarterly_snapshots(store, records)


def test_provider_amount_outside_float_range_is_rejected(tmp_path):
    store = SnapshotStore(tmp_path)
    payloads = sources()
    payloads["CASH_FLOW"]["quarterlyReports"][-1]["operatingCashflow"] = "1e999"
    with pytest.raises(ValueError, match="numeric calculation range"):
        review_quarterly_snapshots(store, capture(store, payloads))
