"""Provider-only snapshot arithmetic and reconciliation with synthetic inputs."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline.fundamental_review import FIELDS, review_fundamental_snapshots
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

NOW = datetime(2022, 2, 1, tzinfo=timezone.utc)


def payloads():
    result = {}
    for function, field in FIELDS.items():
        annual, quarterly = [], []
        for year in (2020, 2021):
            value = 40 if function == "INCOME_STATEMENT" else 32 if function == "CASH_FLOW" else 100 + 20 * (year - 2020)
            row = {"fiscalDateEnding": f"{year}-12-31", "reportedCurrency": "USD", field: str(value)}
            if function == "CASH_FLOW": row["netIncome"] = "40"
            annual.append(row)
            for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
                amount = value if function == "BALANCE_SHEET" else value // 4
                qrow = {**row, "fiscalDateEnding": f"{year}-{month:02d}-{day}", field: str(amount)}
                if function == "CASH_FLOW": qrow["netIncome"] = "10"
                quarterly.append(qrow)
        result[function] = {"symbol": "SYNTH", "annualReports": annual, "quarterlyReports": quarterly}
    return result


def captured(store, sources=None):
    return [store.capture("alpha_vantage", {"function": function, "symbol": "SYNTH"}, json.dumps(payload).encode(),
                          observed_at=NOW) for function, payload in (sources or payloads()).items()]


def frames(store, records):
    manifest = review_fundamental_snapshots(store, records)
    result = [pd.read_parquet(store.root / manifest["tables"][name]["path"])
              for name in ["annual_review", "reconciliation"]]
    return manifest, *result


def test_provider_only_arithmetic_and_reconciliation(tmp_path):
    store = SnapshotStore(tmp_path)
    records = captured(store)
    before = deepcopy(records)
    manifest, annual, checks = frames(store, records)
    assert records == before
    assert len(annual) == 2 and pd.isna(annual.annual_accrual_candidate.iloc[0])
    assert annual.annual_accrual_candidate.iloc[1] == pytest.approx(-8 / 110)
    assert annual.arithmetic_status.tolist() == ["no_preceding_annual_assets", "candidate_only"]
    assert annual.source_income_comparison.eq("exact_match").all()
    assert annual.available_at.isna().all() and annual.identifier_basis.eq("provider_symbol_unmapped").all()
    assert annual.amount_unit_status.eq("provider_common_scale_assumption_unverified").all()
    assert checks.status.value_counts().to_dict() == {"exact_match": 4, "no_preceding_annual_boundary": 2}
    assert len(manifest["provenance"]["input_manifests"]) == 3
    assert review_fundamental_snapshots(store, records) == manifest


def test_source_differences_remain_visible_without_rewriting(tmp_path):
    store = SnapshotStore(tmp_path)
    sources = payloads()
    sources["CASH_FLOW"]["quarterlyReports"][-1]["operatingCashflow"] = "9"
    sources["CASH_FLOW"]["annualReports"][-1]["netIncome"] = "39"
    manifest, annual, checks = frames(store, captured(store, sources))
    assert annual.source_income_difference_text.iloc[-1] == "1"
    assert annual.source_income_comparison.iloc[-1] == "value_difference"
    assert annual.annual_accrual_candidate.iloc[-1] == pytest.approx(-8 / 110)
    difference = checks.loc[checks.status.eq("value_difference")].iloc[0]
    assert difference.annual_value_text == "32" and difference.compared_value_text == "33"
    assert difference.difference_text == "-1"


def test_missing_quarter_does_not_block_direct_annual_review(tmp_path):
    store = SnapshotStore(tmp_path)
    sources = payloads()
    sources["CASH_FLOW"]["quarterlyReports"].pop()
    _, annual, checks = frames(store, captured(store, sources))
    assert annual.arithmetic_status.iloc[-1] == "candidate_only"
    assert "incomplete_quarter_window" in checks.status.tolist()


@pytest.mark.parametrize("issue", ["missing_value", "missing_column", "currency", "spacing"])
def test_quarter_checks_do_not_silently_accept_bad_inputs(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    sources = payloads()
    rows = sources["CASH_FLOW"]["quarterlyReports"]
    if issue == "missing_value": rows[-1]["operatingCashflow"] = "None"
    if issue == "missing_column":
        for row in rows: del row["operatingCashflow"]
    if issue == "currency": rows[-1]["reportedCurrency"] = "CAD"
    if issue == "spacing": rows[-2]["fiscalDateEnding"] = "2021-07-01"
    _, annual, checks = frames(store, captured(store, sources))
    expected = {"missing_value": "missing_amount", "missing_column": "missing_amount",
                "currency": "currency_difference", "spacing": "irregular_quarter_spacing"}[issue]
    assert expected in checks.status.tolist()
    assert annual.arithmetic_status.iloc[-1] == "candidate_only"


@pytest.mark.parametrize("issue", ["missing_income", "zero_assets", "negative_assets", "currency", "annual_gap", "previous_currency"])
def test_incomplete_annual_arithmetic_stays_missing(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    sources = payloads()
    if issue == "missing_income": sources["INCOME_STATEMENT"]["annualReports"][-1]["netIncome"] = "None"
    if issue == "zero_assets": sources["BALANCE_SHEET"]["annualReports"][-1]["totalAssets"] = "0"
    if issue == "negative_assets": sources["BALANCE_SHEET"]["annualReports"][-1]["totalAssets"] = "-1"
    if issue == "currency": sources["CASH_FLOW"]["annualReports"][-1]["reportedCurrency"] = "CAD"
    if issue == "annual_gap":
        for payload in sources.values(): payload["annualReports"][0]["fiscalDateEnding"] = "2019-12-31"
    if issue == "previous_currency":
        for payload in sources.values(): payload["annualReports"][0]["reportedCurrency"] = "CAD"
    _, annual, checks = frames(store, captured(store, sources))
    assert pd.isna(annual.annual_accrual_candidate.iloc[-1])
    assert annual.arithmetic_status.iloc[-1] != "candidate_only"
    if issue == "currency":
        assert annual.source_income_comparison.iloc[-1] == "currency_missing_or_different"
        assert pd.isna(annual.source_income_difference_text.iloc[-1])


@pytest.mark.parametrize("value", ["unparseable", "Infinity", "-Infinity"])
def test_bad_amounts_are_not_silently_coerced(tmp_path, value):
    store = SnapshotStore(tmp_path)
    sources = payloads()
    sources["INCOME_STATEMENT"]["annualReports"][-1]["netIncome"] = value
    with pytest.raises(ValueError):
        review_fundamental_snapshots(store, captured(store, sources))


def test_outer_alignment_retains_unmatched_annual_period(tmp_path):
    store = SnapshotStore(tmp_path)
    sources = payloads()
    sources["CASH_FLOW"]["annualReports"][-1]["fiscalDateEnding"] = "2021-12-30"
    _, annual, checks = frames(store, captured(store, sources))
    assert len(annual) == 3 and annual.annual_accrual_candidate.isna().all()


@pytest.mark.parametrize("issue", ["missing_endpoint", "duplicate_endpoint", "different_symbol", "raw_corruption", "table_corruption"])
def test_input_dependencies_are_checked_before_cached_review(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    records = captured(store)
    manifest = review_fundamental_snapshots(store, records)
    if issue == "missing_endpoint": records.pop()
    if issue == "duplicate_endpoint": records[-1] = records[0]
    if issue == "different_symbol":
        request = json.loads(records[0]["request_json"]); request["symbol"] = "OTHER"
        records[0] = {**records[0], "request_json": json.dumps(request)}
    if issue == "raw_corruption": (store.root / records[0]["raw_path"]).write_text("{}")
    if issue == "table_corruption": (store.root / manifest["tables"]["annual_review"]["path"]).write_bytes(b"bad")
    with pytest.raises(ValueError):
        review_fundamental_snapshots(store, records)


def test_new_observation_creates_an_independent_review_version(tmp_path):
    store = SnapshotStore(tmp_path)
    first = frames(store, captured(store))[0]
    second = frames(store, captured(store))[0]
    assert first["snapshot_id"] != second["snapshot_id"]
    assert first["normalizer"] != second["normalizer"]


def test_noncalendar_year_uses_observed_annual_boundaries(tmp_path):
    store = SnapshotStore(tmp_path)
    sources = payloads()
    for payload in sources.values():
        for kind in ["annualReports", "quarterlyReports"]:
            for row in payload[kind]:
                row["fiscalDateEnding"] = (pd.Timestamp(row["fiscalDateEnding"]) - pd.DateOffset(months=2)).date().isoformat()
    _, annual, checks = frames(store, captured(store, sources))
    assert annual.annual_accrual_candidate.iloc[-1] == pytest.approx(-8 / 110)
    assert checks.status.value_counts()["exact_match"] == 4


def test_unrepresentable_ratio_is_not_emitted_as_infinity(tmp_path):
    store = SnapshotStore(tmp_path)
    sources = payloads()
    sources["INCOME_STATEMENT"]["annualReports"][-1]["netIncome"] = "1e999"
    _, annual, checks = frames(store, captured(store, sources))
    assert pd.isna(annual.annual_accrual_candidate.iloc[-1])
    assert annual.arithmetic_status.iloc[-1] == "outside_float_range"
