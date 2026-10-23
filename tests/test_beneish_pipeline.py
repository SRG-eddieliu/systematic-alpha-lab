"""A real offline store exercises source selection separately from model math."""
import hashlib
import json
import socket
from copy import deepcopy

import pandas as pd
import pytest
import requests

from systematic_alpha_lab.data_pipeline.fundamental_snapshots import replay_fundamentals
from systematic_alpha_lab.data_pipeline.offline_reader import DataRead, OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.factor_research.beneish_pipeline import (
    AV_CANDIDATES,
    FUNCTIONS,
    review_annual_beneish_snapshots,
)


def make_store(tmp_path, *, missing_cf_prior=False, missing_dep=False, wrong_cf_currency=False):
    store = SnapshotStore(tmp_path / "source")
    values = {"trade_receivables_net": 20, "current_assets": 60, "current_liabilities": 40,
              "total_assets": 200, "net_ppe": 70, "long_term_debt_noncurrent": 15, "sales": 200,
              "cost_of_goods_sold": 140, "depreciation": 10, "sga_expense": 15,
              "income_before_extraordinary_items": 10, "operating_cash_flow": 10}
    selection = {}
    for function in FUNCTIONS:
        annual = []
        for year in (2019, 2020):
            if missing_cf_prior and function == "CASH_FLOW" and year == 2019:
                continue
            row = {"fiscalDateEnding": f"{year}-12-31", "reportedCurrency": "EUR" if wrong_cf_currency and function == "CASH_FLOW" else "USD"}
            row.update({field: str(values[name]) for name, (source, field) in AV_CANDIDATES.items() if source == function})
            if missing_dep and function == "INCOME_STATEMENT":
                row["depreciation"] = "None"
                row["depreciationAndAmortization"] = "10"
            annual.append(row)
        payload = {"symbol": "SYNTH", "annualReports": annual, "quarterlyReports": []}
        record = store.capture("alpha_vantage", {"function": function, "symbol": "SYNTH"},
                               json.dumps(payload).encode(), observed_at="2021-02-01T00:00:00+00:00")
        replay_fundamentals(store, record)
        selection[function] = record["id"]
    context = {
        "selection": selection.copy(),
        "periods": {f"{year}-12-31": {
            "entity_id": "synthetic-issuer", "fiscal_year": year, "period_start": f"{year}-01-01",
            "unit_scale": 1, "reporting_scope": "consolidated", "accounting_basis": "synthetic_us_gaap",
            "flow_basis": "annual", "metadata_evidence": "Synthetic fixture, not a real filing",
        } for year in (2019, 2020)},
        "field_mappings": {name: {"status": "verified_exact", "evidence": "Synthetic fixture explicitly generated in this concept"}
                           for name in AV_CANDIDATES},
    }
    return store, selection, context


def fingerprints(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_public_synthetic_pipeline_roundtrip_is_offline_immutable_and_not_research_ready(tmp_path, monkeypatch):
    store, selection, context = make_store(tmp_path)
    before, declaration = fingerprints(store.root), deepcopy(context)

    def forbidden(*args, **kwargs):
        raise AssertionError("Network attempted")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    result = review_annual_beneish_snapshots(OfflineDataReader(store.root), symbol="SYNTH", snapshot_ids=selection, context=context)
    assert result["period_count"] == 2 and result["calculation_ready_count"] == 1
    assert result["rows"][0]["m_score"] is None
    assert result["rows"][1]["m_score"] == pytest.approx(-2.48)
    assert result["rows"][1]["flag"] is None
    assert result["research_ready"] is False and result["network_calls"] == 0
    assert result["timing_status"] == "snapshot_only_availability_unverified"
    assert fingerprints(store.root) == before and context == declaration
    json.dumps(result, allow_nan=False)


def test_without_context_no_identity_unit_or_dates_are_invented(tmp_path):
    store, selection, _ = make_store(tmp_path)
    result = review_annual_beneish_snapshots(OfflineDataReader(store.root), symbol="SYNTH", snapshot_ids=selection)
    assert result["calculation_ready_count"] == 0
    assert all(row["m_score"] is None and row["standard_definition_satisfied"] is False for row in result["rows"])


def test_pinned_source_context_cannot_move_to_new_selection(tmp_path):
    store, selection, context = make_store(tmp_path)
    context["selection"]["CASH_FLOW"] = "0" * 32
    with pytest.raises(ValueError, match="exact source selection"):
        review_annual_beneish_snapshots(OfflineDataReader(store.root), symbol="SYNTH", snapshot_ids=selection, context=context)


def test_wrong_function_or_symbol_cannot_join(tmp_path):
    store, selection, _ = make_store(tmp_path)
    for symbol, pins in (("OTHER", selection), ("SYNTH", selection | {"CASH_FLOW": selection["INCOME_STATEMENT"]})):
        with pytest.raises(ValueError, match="function/symbol"):
            review_annual_beneish_snapshots(OfflineDataReader(store.root), symbol=symbol, snapshot_ids=pins)


@pytest.mark.parametrize("field,value", [("snapshot_id", "0" * 32), ("normalizer", "other_v1"), ("table", "quarterly")])
def test_returned_source_identity_must_match_the_requested_pins(tmp_path, field, value):
    store, selection, context = make_store(tmp_path)
    real = OfflineDataReader(store.root)

    class WrongIdentityReader:
        def read(self, **kwargs):
            result = real.read(**kwargs)
            return DataRead(frame=result.frame, metadata=result.metadata | {field: value})

    with pytest.raises(ValueError, match="source identity"):
        review_annual_beneish_snapshots(WrongIdentityReader(), symbol="SYNTH", snapshot_ids=selection, context=context)


def test_prior_cfo_not_required_and_missing_period_is_not_inner_joined_away(tmp_path):
    store, selection, context = make_store(tmp_path, missing_cf_prior=True)
    result = review_annual_beneish_snapshots(OfflineDataReader(store.root), symbol="SYNTH", snapshot_ids=selection, context=context)
    assert result["period_count"] == 2 and result["calculation_ready_count"] == 1
    assert result["rows"][1]["m_score"] == pytest.approx(-2.48)


def test_da_cannot_fill_pure_depreciation_and_currency_cannot_be_overridden(tmp_path):
    for name, kwargs in (("depreciation", {"missing_dep": True}), ("currency", {"wrong_cf_currency": True})):
        folder = tmp_path / name
        store, selection, context = make_store(folder, **kwargs)
        result = review_annual_beneish_snapshots(OfflineDataReader(store.root), symbol="SYNTH", snapshot_ids=selection, context=context)
        assert result["calculation_ready_count"] == 0


def test_reviewed_field_status_without_evidence_is_not_accepted(tmp_path):
    store, selection, context = make_store(tmp_path)
    context["field_mappings"]["trade_receivables_net"].pop("evidence")
    result = review_annual_beneish_snapshots(OfflineDataReader(store.root), symbol="SYNTH", snapshot_ids=selection, context=context)
    assert result["calculation_ready_count"] == 0


def test_ambiguous_source_periods_reject_instead_of_multiplying_rows(tmp_path):
    store, selection, _ = make_store(tmp_path)
    real = OfflineDataReader(store.root)

    class DuplicateReader:
        def read(self, **kwargs):
            result = real.read(**kwargs)
            return DataRead(frame=pd.concat([result.frame, result.frame.iloc[[0]]], ignore_index=True), metadata=result.metadata)

    with pytest.raises(ValueError, match="ambiguous"):
        review_annual_beneish_snapshots(DuplicateReader(), symbol="SYNTH", snapshot_ids=selection)
