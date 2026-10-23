"""A bounded candidate run keeps its contract, every source and explicit gaps."""
import hashlib
import json
import socket
from copy import deepcopy

import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.data_pipeline.supplemental_pilot import (
    collect_yfinance_pilot,
    validate_pilot_plan,
    verify_yfinance_pilot,
)

NOW = "2026-01-15T12:00:00+00:00"


def plan():
    result = {"schema_version": 1, "targets": [{"symbol": "SYNTH", "cik": "0000000001",
             "company_ref": "synthetic issuer only", "periods": [
                 {"fiscal_year": 2024, "start": "2024-01-01", "end": "2024-12-31"},
                 {"fiscal_year": 2025, "start": "2025-01-01", "end": "2025-12-31"},
             ]}], "research_contract": {"status": "synthetic_not_financial_acceptance", "fields": ["Depreciation"]}}
    result["research_contract"]["scope"] = {"issuers": [{"yahoo_symbol": "SYNTH", "cik": "0000000001", "periods": [
        {"fiscal_year": p["fiscal_year"], "period_start": p["start"], "period_end": p["end"]}
        for p in result["targets"][0]["periods"]
    ]}]}
    return result


def fake_collector(symbols, *, max_session_requests):
    assert symbols == ["SYNTH"] and max_session_requests == 40
    raw = {"timeseries": {"error": None, "result": [{
        "meta": {"symbol": ["SYNTH"], "type": ["annualDepreciation"]},
        "timestamp": [1735603200, 1767139200], "annualDepreciation": [
            {"asOfDate": "2024-12-31", "periodType": "12M", "currencyCode": "USD",
             "reportedValue": {"raw": 9007199254740993, "fmt": "9Q"}},
            {"asOfDate": "2025-12-31", "periodType": "12M", "currencyCode": "USD",
             "reportedValue": {"raw": 42, "fmt": "42"}},
        ]}]}}
    return {"results": [{"symbol": "SYNTH", "method": "get_income_stmt", "statement": "income",
                         "frame": pd.DataFrame([[9007199254740992.0, 42.0]], index=["Depreciation"],
                                               columns=pd.to_datetime(["2024-12-31", "2025-12-31"])),
                         "started_at": NOW, "finished_at": NOW, "yfinance_version": "1.7.0"}],
            "http_captures": [{"symbol": "SYNTH", "statement": "income", "observed_at": NOW,
                               "body": json.dumps(raw).encode()}],
            "request_observations": [{"route": "financial_timeseries", "status": 200}],
            "stopped": True, "stop_reason": "synthetic_partial", "session_request_count": 1}


def fingerprints(root):
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def test_partial_capture_replays_all_layers_without_network_writer_or_changes(tmp_path, monkeypatch):
    root = tmp_path / "new"
    receipt = collect_yfinance_pilot(root, plan=plan(), code_commit="1" * 40, collector=fake_collector)
    assert receipt["collection"]["logical_results"] == 1
    assert receipt["collection"]["accepted_research_fields"] == 0
    before = fingerprints(root)

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline verification attempted a network request or writable store")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(SnapshotStore, "__init__", forbidden)
    monkeypatch.setattr(SnapshotStore, "latest", forbidden)
    result = verify_yfinance_pilot(root)
    assert result["tables"] == 5 and result["collection_stopped"]
    assert result["accepted_research_fields"] == 0
    assert fingerprints(root) == before


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(targets=[]),
    lambda p: p["targets"][0].update(cik="1"),
    lambda p: p["targets"][0].update(symbol="../bad"),
    lambda p: p["targets"][0].update(periods=p["targets"][0]["periods"][:1]),
    lambda p: p["targets"][0]["periods"][1].update(start="2025-02-01"),
    lambda p: p["targets"][0]["periods"][1].update(fiscal_year=2027),
    lambda p: p.update(targets=p["targets"] * 4),
    lambda p: p.update(research_contract={}),
    lambda p: p["targets"][0].update(cik="0000000002"),
])
def test_invalid_bound_or_period_preflight_makes_no_calls_or_root(tmp_path, mutation):
    value = plan()
    mutation(value)
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid plan attempted collection")
    with pytest.raises(ValueError):
        collect_yfinance_pilot(tmp_path / "new", plan=value, code_commit="1" * 40, collector=forbidden)
    assert not (tmp_path / "new").exists()


def test_existing_root_is_not_resumed_or_changed(tmp_path):
    root = tmp_path / "closed"
    root.mkdir()
    (root / "sentinel").write_text("closed")
    before = fingerprints(root)
    with pytest.raises(ValueError):
        collect_yfinance_pilot(root, plan=plan(), code_commit="1" * 40, collector=fake_collector)
    assert fingerprints(root) == before


@pytest.mark.parametrize("mutation", [
    lambda r: r["plan"]["research_contract"].update(status="silently_changed"),
    lambda r: r["captures"].pop(),
    lambda r: r["captures"][0]["manifest"].update(tables={}),
    lambda r: r["anchor_manifest"]["tables"].update(extra=deepcopy(r["anchor_manifest"]["tables"]["audit"])),
    lambda r: r["collection"].update(session_request_count=0),
    lambda r: r["collection"].update(logical_attempts=[]),
])
def test_contract_and_incomplete_or_changed_receipts_rejected(tmp_path, mutation):
    root = tmp_path / "new"
    receipt = collect_yfinance_pilot(root, plan=plan(), code_commit="1" * 40, collector=fake_collector)
    mutation(receipt)
    (root / "pilot-receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        verify_yfinance_pilot(root)


def test_plan_validation_does_not_claim_issuer_or_accounting_acceptance():
    assert validate_pilot_plan(plan()) == ["SYNTH"]


def test_unsupported_dataframe_does_not_lose_completed_transport_evidence(tmp_path):
    def collect(symbols, **kwargs):
        value = fake_collector(symbols, **kwargs)
        value["results"][0]["frame"] = pd.DataFrame([[object()]], index=["Depreciation"], columns=[pd.Timestamp("2025-12-31")])
        return value
    receipt = collect_yfinance_pilot(tmp_path / "new", plan=plan(), code_commit="1" * 40, collector=collect)
    assert len(receipt["captures"]) == 1
    assert receipt["rejected_library_returns"][0]["safe_error_class"] == "TypeError"
    assert len(receipt["collection"]["logical_attempts"]) == 3
    assert (tmp_path / "new" / "transport-receipt.json").exists()
    assert verify_yfinance_pilot(tmp_path / "new")["tables"] == 3
