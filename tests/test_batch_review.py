"""Bounded multi-company diagnostics and pinned selection failure contracts."""
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline.batch_review import review_fundamental_batch
from systematic_alpha_lab.data_pipeline.fundamental_review import FIELDS
from systematic_alpha_lab.data_pipeline.fundamental_snapshots import FUNCTIONS
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def add_company(store, symbol="SYN-A", *, dates=None, income=10, currency="USD", observed="2025-01-01T00:00:00Z"):
    dates = list(pd.date_range("2021-06-30", periods=9, freq=pd.offsets.QuarterEnd())) if dates is None else dates
    result = []
    for function, field in FIELDS.items():
        value = income if function == "INCOME_STATEMENT" else 8
        quarterly = [{"fiscalDateEnding": str(pd.Timestamp(date).date()), "reportedCurrency": currency,
                      field: str(100 + i * 10 if function == "BALANCE_SHEET" else value)}
                     for i, date in enumerate(dates)]
        if function == "CASH_FLOW":
            for row in quarterly:
                row["netIncome"] = str(income)
        annual = [{**quarterly[i], field: quarterly[i][field] if function == "BALANCE_SHEET" else str(4 * value)}
                  for i in (0, 4, 8)]
        if function == "CASH_FLOW":
            for row in annual:
                row["netIncome"] = str(income * 4)
        payload = {"symbol": symbol, "annualReports": annual, "quarterlyReports": quarterly}
        result.append(store.capture("alpha_vantage", {"function": function, "symbol": symbol},
                                    json.dumps(payload).encode(), observed_at=observed))
    return result


def table(store, result, name):
    return pd.read_parquet(store.root / result["manifest"]["tables"][name]["path"])


def test_companies_with_equal_dates_and_different_currencies_never_pool_amounts(tmp_path, monkeypatch):
    import requests
    def no_network(*args, **kwargs):
        pytest.fail("An offline batch attempted a network request")
    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    store = SnapshotStore(tmp_path)
    add_company(store)
    add_company(store, "SYN-B", income=20, currency="CAD")
    result = review_fundamental_batch(store, symbols=["SYN-B", "SYN-A"])
    assert result["status"] == "complete"
    assert [row["provider_symbol"] for row in result["summary"]] == ["SYN-A", "SYN-B"]
    quarters = table(store, result, "quarterly_review")
    assert len(quarters) == 18
    assert not quarters.duplicated(["provider_symbol", "period_end"]).any()
    for symbol, expected, currency in [("SYN-A", -8 / 120, "USD"), ("SYN-B", -48 / 120, "CAD")]:
        rows = quarters[quarters.provider_symbol.eq(symbol)]
        assert rows.accrual_quality.iloc[4] == pytest.approx(expected)
        assert set(rows.currency) == {currency}
        assert rows.available_at.isna().all()
    assert len(table(store, result, "reconciliation")) == 18
    assert all(row["ttm_candidate_rows"] == 5 for row in result["summary"])
    assert all(row["observed_annual_end_months"] == "[6]" for row in result["summary"])
    assert review_fundamental_batch(store, symbols=["SYN-A", "SYN-B"], snapshot_ids=result["selection"]) == result


def test_53_week_year_and_changing_endpoint_month_are_observed_without_quarter_inference(tmp_path):
    store = SnapshotStore(tmp_path)
    dates = pd.to_datetime(["2021-09-25", "2021-12-25", "2022-03-26", "2022-06-25", "2022-10-01",
                            "2022-12-31", "2023-04-01", "2023-07-01", "2023-09-30"])
    add_company(store, dates=dates)
    result = review_fundamental_batch(store, symbols=["SYN-A"])
    assert result["summary"][0]["observed_annual_end_months"] == "[9, 10]"
    assert result["summary"][0]["annual_candidate_rows"] == 2
    assert result["summary"][0]["ttm_candidate_rows"] == 5
    assert "fiscal_quarter" not in table(store, result, "quarterly_review")


def test_missing_company_is_visible_and_a_pinned_missing_input_stays_missing(tmp_path):
    store = SnapshotStore(tmp_path)
    add_company(store)
    partial = review_fundamental_batch(store, symbols=["SYN-A", "SYN-B"])
    assert partial["status"] == "partial"
    assert partial["summary"][1]["status"] == "missing_captures"
    assert partial["summary"][1]["quarterly_rows"] is None
    assert table(store, partial, "coverage").quarterly_rows.isna().sum() == 1
    add_company(store, "SYN-B")
    assert review_fundamental_batch(store, symbols=["SYN-A", "SYN-B"], snapshot_ids=partial["selection"]) == partial
    assert review_fundamental_batch(store, symbols=["SYN-A", "SYN-B"])["status"] == "complete"


def test_newer_capture_does_not_change_pinned_replay(tmp_path):
    store = SnapshotStore(tmp_path)
    old_records = add_company(store)
    original = review_fundamental_batch(store, symbols=["SYN-A"])
    add_company(store, income=30, observed="2026-01-01T00:00:00Z")
    assert store.get(old_records[0]["id"]) == old_records[0]
    assert review_fundamental_batch(store, symbols=["SYN-A"], snapshot_ids=original["selection"]) == original
    latest = review_fundamental_batch(store, symbols=["SYN-A"])
    assert latest["selection"] != original["selection"]
    assert latest["manifest"]["normalizer"] != original["manifest"]["normalizer"]


@pytest.mark.parametrize("damage", ["raw", "normalized", "absent_raw"])
def test_source_failure_isolated_to_one_company_including_after_successful_replay(tmp_path, damage):
    store = SnapshotStore(tmp_path)
    add_company(store)
    damaged = add_company(store, "SYN-B")
    original = review_fundamental_batch(store, symbols=["SYN-A", "SYN-B"])
    if damage == "normalized":
        path = store.root / original["manifest"]["provenance"]["company_manifests"]["SYN-B"]["tables"]["quarterly_review"]["path"]
        path.write_bytes(b"corrupt")
    else:
        path = store.root / damaged[0]["raw_path"]
        # Distinct symbol bodies guarantee we only damage SYN-B's shared objects.
        path.unlink() if damage == "absent_raw" else path.write_bytes(b"corrupt")
    result = review_fundamental_batch(store, symbols=["SYN-A", "SYN-B"], snapshot_ids=original["selection"])
    assert result["status"] == "partial"
    assert [row["status"] for row in result["summary"]] == ["review_ready", "source_rejected"]
    assert set(table(store, result, "quarterly_review").provider_symbol) == {"SYN-A"}


def test_combined_table_corruption_is_not_silently_republished(tmp_path):
    store = SnapshotStore(tmp_path)
    add_company(store)
    result = review_fundamental_batch(store, symbols=["SYN-A"])
    (store.root / result["manifest"]["tables"]["coverage"]["path"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        review_fundamental_batch(store, symbols=["SYN-A"], snapshot_ids=result["selection"])


@pytest.mark.parametrize("issue", ["gap", "currency_change"])
def test_bad_windows_stay_local_and_are_not_filled_from_other_companies(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    add_company(store)
    records = add_company(store, "SYN-B")
    for record in records:
        payload = store.read_payload(record)
        if issue == "gap":
            del payload["quarterlyReports"][2]
        else:
            for row in payload["quarterlyReports"][4:]:
                row["reportedCurrency"] = "CAD"
        store.capture("alpha_vantage", json.loads(record["request_json"]), json.dumps(payload).encode(),
                      observed_at="2026-01-01T00:00:00Z")
    result = review_fundamental_batch(store, symbols=["SYN-A", "SYN-B"])
    assert result["status"] == "complete"
    rows = table(store, result, "quarterly_review")
    assert rows[rows.provider_symbol.eq("SYN-A")].calculation_ready.sum() == 5
    assert rows[rows.provider_symbol.eq("SYN-B")].calculation_ready.sum() == (2 if issue == "gap" else 1)


def test_all_rejected_remain_visible_without_an_aggregate(tmp_path):
    store = SnapshotStore(tmp_path)
    records = add_company(store)
    (store.root / records[0]["raw_path"]).write_bytes(b"corrupt")
    result = review_fundamental_batch(store, symbols=["SYN-A"])
    assert result["status"] == "no_usable_symbols"
    assert result["summary"][0]["status"] == "source_rejected"
    assert result["manifest"] is None


@pytest.mark.parametrize("symbols", [[], ["SYN-A", "SYN-A"], ["bad symbol"], [None], "SYN-A"])
def test_invalid_explicit_samples_rejected(tmp_path, symbols):
    with pytest.raises(ValueError):
        review_fundamental_batch(SnapshotStore(tmp_path), symbols=symbols)


@pytest.mark.parametrize("selection", [{}, {"SYN-A": {}}, {"SYN-A": None},
    {"SYN-A": {function: "invalid" for function in FUNCTIONS}}])
def test_incomplete_or_invalid_pinned_selections_do_not_fall_back(tmp_path, selection):
    store = SnapshotStore(tmp_path)
    add_company(store)
    with pytest.raises(ValueError):
        review_fundamental_batch(store, symbols=["SYN-A"], snapshot_ids=selection)


def test_cross_company_or_cross_statement_selection_rejected(tmp_path):
    store = SnapshotStore(tmp_path)
    first, second = add_company(store), add_company(store, "SYN-B")
    selection = {"SYN-A": {json.loads(record["request_json"])["function"]: record["id"] for record in first}}
    for record in second[:1] + first[1:2]:
        selection["SYN-A"]["INCOME_STATEMENT"] = record["id"]
        with pytest.raises(ValueError, match="another company or statement"):
            review_fundamental_batch(store, symbols=["SYN-A"], snapshot_ids=selection)


def test_all_missing_returns_receipt_without_fabricated_dataset(tmp_path):
    result = review_fundamental_batch(SnapshotStore(tmp_path), symbols=["SYN-A"])
    assert result["status"] == "no_usable_symbols"
    assert result["manifest"] is None
    assert result["summary"][0]["annual_rows"] is None
    assert result["selection"] == {"SYN-A": dict.fromkeys(FUNCTIONS)}


def test_missing_exact_identifier_does_not_fall_back_to_existing_latest(tmp_path):
    store = SnapshotStore(tmp_path)
    add_company(store)
    selection = {"SYN-A": {function: "0" * 32 for function in FUNCTIONS}}
    assert store.get("0" * 32) is None
    result = review_fundamental_batch(store, symbols=["SYN-A"], snapshot_ids=selection)
    assert result["status"] == "no_usable_symbols"
    assert result["selection"] == selection


def test_cli_partial_and_empty_status_and_pinned_replay(tmp_path):
    store = SnapshotStore(tmp_path / "data")
    add_company(store)
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "examples/review_fundamental_batch.py"),
               "--data-root", str(store.root)]
    partial = subprocess.run(command + ["--symbols", "SYN-A", "SYN-B"], capture_output=True, text=True)
    assert partial.returncode == 2, partial.stderr
    receipt = tmp_path / "receipt.json"
    receipt.write_text(partial.stdout)
    replay = subprocess.run(command + ["--replay-receipt", str(receipt)], capture_output=True, text=True)
    assert replay.returncode == 2, replay.stderr
    assert json.loads(replay.stdout) == json.loads(partial.stdout)
    empty = subprocess.run(command + ["--symbols", "SYN-B"], capture_output=True, text=True)
    assert empty.returncode == 1
    assert json.loads(empty.stdout)["status"] == "no_usable_symbols"
