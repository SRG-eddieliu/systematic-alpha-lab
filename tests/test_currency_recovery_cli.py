"""Synthetic CLI integration: immutable baseline, exact pins and full coverage."""
import fcntl
import hashlib
import importlib.util
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from systematic_alpha_lab.data_pipeline.alpha_vantage_rest import AlphaVantageError, JSONResponse
from systematic_alpha_lab.data_pipeline.fundamental_batch import (
    create_fundamental_batch,
    read_fundamental_batch,
    run_fundamental_batch,
)
from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.data_pipeline.universe import freeze_universe, write_universe

SPEC = importlib.util.spec_from_file_location(
    "currency_recovery_cli", Path(__file__).parents[1] / "examples/recover_currency_statements.py"
)
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)
COMMIT = "a" * 40


class Clock:
    def __init__(self):
        self.now = datetime(2001, 4, 2, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


def payload(function="INCOME_STATEMENT", currency="USD"):
    annual = [{"fiscalDateEnding": "2000-12-31", "reportedCurrency": currency, "netIncome": "100"}]
    quarterly = [{"fiscalDateEnding": "2001-03-31", "reportedCurrency": currency, "netIncome": "25"}]
    if function == "BALANCE_SHEET":
        quarterly += [{"fiscalDateEnding": "2000-12-31", "reportedCurrency": "USD", "netIncome": "24"},
                      {"fiscalDateEnding": "2000-09-30", "reportedCurrency": "None", "netIncome": "23"}]
    return {"symbol": "SYNTH", "annualReports": annual, "quarterlyReports": quarterly}


class Feed:
    def fetch_json_response(self, function, params):
        if params["symbol"] == "EMPTY":
            raise AlphaVantageError("invalid_or_empty_json")
        content = payload(function, "None" if function == "CASH_FLOW" else "USD")
        return JSONResponse(content, json.dumps(content).encode())


@pytest.fixture
def baseline(tmp_path):
    source = tmp_path / "source"
    store, clock = SnapshotStore(source), Clock()
    universe = freeze_universe([{
        "security_id": "synthetic-security-" + symbol, "company_id": "synthetic-company-" + symbol,
        "company_name": "Synthetic " + symbol, "security_name": "Synthetic " + symbol,
        "source_symbol": symbol, "provider": "alpha_vantage", "provider_symbol": symbol,
        "provider_symbol_status": "verified", "mapping_evidence": ["https://example.invalid/mapping"],
    } for symbol in ("SYNTH", "EMPTY")], {
        "source_url": "https://example.invalid/universe", "captured_at": "2001-04-02T00:00:00Z",
        "as_of": "2001-04-02", "raw_sha256": hashlib.sha256(b"synthetic universe").hexdigest(),
        "kind": "secondary_index", "source_status": "unknown",
        "verification": {"status": "unverified", "scope": "unverified", "method": None, "evidence_urls": []},
    }, index_name="Synthetic universe")
    universe_path = write_universe(universe, tmp_path / "universe.json")
    create_fundamental_batch(store, run_id="synthetic", symbols=["SYNTH", "EMPTY"],
                             universe_sha256=universe["manifest_sha256"], max_requests=6,
                             min_interval_seconds=1, universe_scope="secondary_index", clock=clock)
    ledger = run_fundamental_batch(Feed(), store, run_id="synthetic", max_requests=6,
                                    clock=clock, sleep=clock.sleep)
    # An unselected newer observation must never replace the failed attempt.
    newer = payload()
    newer["quarterlyReports"][0]["netIncome"] = "99999"
    store.capture("alpha_vantage", {"function": "BALANCE_SHEET", "symbol": "SYNTH"}, json.dumps(newer).encode(),
                  observed_at="2001-04-03T00:00:00Z")
    return {"source_root": source, "output_root": tmp_path / "recovery", "run_id": "synthetic",
            "universe": universe_path, "code_commit": COMMIT}, ledger


def block_network(monkeypatch):
    from systematic_alpha_lab.data_pipeline import config_loader

    def denied(*args, **kwargs):
        raise AssertionError("Recovery attempted a network request or latest selection")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(requests.Session, "request", denied)
    monkeypatch.setattr(SnapshotStore, "latest", denied)
    monkeypatch.setattr(config_loader, "load_credentials", denied)


def test_cli_recovers_exact_failed_pins_in_independent_copy_and_retains_every_job(baseline, monkeypatch, capsys):
    args, ledger = baseline
    before = cli.inventory(args["source_root"])
    block_network(monkeypatch)
    cli.main([part for key, value in args.items() for part in ("--" + key.replace("_", "-"), str(value))])
    printed = capsys.readouterr().out
    summary = json.loads(printed)
    assert summary["planned_jobs"] == 6 and summary["network_requests"] == 0
    assert summary["coverage"] == {
        "original_success_jobs": 1, "recovered_with_usable_rows_jobs": 1, "still_no_usable_data_jobs": 4,
        "recovery_attempted_jobs": 2, "recovery_materialized_jobs": 2, "quarantine_only_jobs": 1,
        "recovery_rejected_jobs": 0, "accepted_recovery_rows": 3, "quarantined_rows": 3,
    }
    assert summary["eligibility"] == "not_certified" and summary["source_files_unchanged"]
    assert "SYNTH" not in printed and "snapshot_id" not in printed and str(args["source_root"]) not in printed
    assert cli.inventory(args["source_root"]) == before
    assert read_fundamental_batch(args["output_root"], run_id="synthetic") == ledger
    metadata = args["output_root"] / "fundamental_recoveries/synthetic"
    manifest = json.loads((metadata / "manifest.json").read_bytes())
    receipts = json.loads((metadata / "receipts.json").read_bytes())
    assert len(manifest["jobs"]) == 6 and manifest["parent_manifest_sha256"] == ledger["manifest_sha256"]
    assert manifest["code_commit"] == COMMIT and manifest["selection_sha256"] == summary["selection_sha256"]
    assert (metadata / "universe.json").read_bytes() == args["universe"].read_bytes()
    assert len(receipts["original_success_receipts"]) == 1 and len(receipts["recovery_receipts"]) == 2
    reader = OfflineDataReader(args["output_root"])
    for receipt in receipts["original_success_receipts"] + receipts["recovery_receipts"]:
        cli._verify_receipt(reader, receipt)
    balance = next(receipt for receipt in receipts["recovery_receipts"]
                   if receipt["request"]["function"] == "BALANCE_SHEET")
    failed_attempt = ledger["jobs"][1]["attempts"][-1]
    assert balance["snapshot_id"] == failed_attempt["snapshot_id"]
    assert balance["raw_sha256"] == failed_attempt["raw_sha256"]
    result = reader.read(snapshot_id=balance["snapshot_id"], normalizer=balance["normalizer"], table="quarterly")
    assert result.frame.netIncome.tolist() == ["24", "25"]
    source_catalog, output_catalog = args["source_root"] / "catalog.sqlite3", args["output_root"] / "catalog.sqlite3"
    assert (source_catalog.stat().st_dev, source_catalog.stat().st_ino) != (
        output_catalog.stat().st_dev, output_catalog.stat().st_ino
    )
    with pytest.raises(ValueError, match="new directory"):
        cli.recover(**args)
    assert cli.inventory(args["source_root"]) == before


@pytest.mark.parametrize("sidecar", ["catalog.sqlite3-journal", "catalog.sqlite3-wal", "catalog.sqlite3-shm"])
def test_recovery_rejects_journal_sidecars_before_creating_output(baseline, sidecar):
    args, _ = baseline
    (args["source_root"] / sidecar).write_bytes(b"synthetic sidecar")
    with pytest.raises(ValueError, match="journal sidecars"):
        cli.recover(**args)
    assert not args["output_root"].exists()


def test_recovery_rejects_an_active_source_writer_before_copying(baseline):
    args, _ = baseline
    with (args["source_root"] / cli.LOCK).open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="active"):
            cli.recover(**args)
    assert not args["output_root"].exists()


def test_recovery_rejects_symlinks_overlap_and_universe_mismatch(baseline):
    args, _ = baseline
    for output in (args["source_root"], args["source_root"] / "inside", args["source_root"].parent):
        with pytest.raises(ValueError, match="overlap"):
            cli.recover(**dict(args, output_root=output))
    link = args["source_root"] / "bad-link"
    link.symlink_to(args["universe"])
    with pytest.raises(ValueError, match="symlink"):
        cli.recover(**args)
    link.unlink()
    changed = json.loads(args["universe"].read_bytes())
    changed["manifest_sha256"] = "f" * 64
    args["universe"].write_text(json.dumps(changed))
    with pytest.raises(ValueError):
        cli.recover(**args)
    assert not args["output_root"].exists()


def test_recovery_detects_a_source_change_during_copy(baseline, monkeypatch):
    args, _ = baseline
    copytree = cli.shutil.copytree

    def changed_after_copy(source, output, *positional, **kwargs):
        result = copytree(source, output, *positional, **kwargs)
        if Path(source) == args["source_root"]:
            (Path(source) / "unexpected-writer").write_bytes(b"synthetic mutation")
        return result

    monkeypatch.setattr(cli.shutil, "copytree", changed_after_copy)
    with pytest.raises(ValueError, match="Source changed"):
        cli.recover(**args)
    assert not (args["output_root"] / "fundamental_recoveries/synthetic/manifest.json").exists()


def test_recovery_rejects_tampered_attempt_pins_without_publishing_manifest(baseline):
    args, _ = baseline
    path = args["source_root"] / "fundamental_batches/synthetic/manifest.json"
    ledger = json.loads(path.read_bytes())
    ledger["jobs"][1]["attempts"][-1]["raw_sha256"] = "f" * 64
    ledger.pop("manifest_sha256")
    ledger["manifest_sha256"] = cli._sha(ledger)
    path.write_text(json.dumps(ledger))
    before = cli.inventory(args["source_root"])
    with pytest.raises(ValueError, match="raw pins differ"):
        cli.recover(**args)
    assert cli.inventory(args["source_root"]) == before
    assert not (args["output_root"] / "fundamental_recoveries/synthetic/manifest.json").exists()


@pytest.mark.parametrize("change", ["empty", "omitted_table"])
def test_recovery_rejects_rehashed_success_ledger_with_incomplete_table_pin(baseline, change):
    args, _ = baseline
    path = args["source_root"] / "fundamental_batches/synthetic/manifest.json"
    ledger = json.loads(path.read_bytes())
    success = next(job for job in ledger["jobs"] if job["status"] == "succeeded")
    if change == "empty":
        success["pin"]["tables"] = {}
    else:
        success["pin"]["tables"].pop("quarterly")
    ledger.pop("manifest_sha256")
    ledger["manifest_sha256"] = cli._sha(ledger)
    path.write_text(json.dumps(ledger))
    # The batch ledger is internally rehashed and accepted by its own loader.
    assert read_fundamental_batch(args["source_root"], run_id="synthetic") == ledger
    before = cli.inventory(args["source_root"])
    with pytest.raises(ValueError, match="complete.*table set"):
        cli.recover(**args)
    assert cli.inventory(args["source_root"]) == before
    assert not (args["output_root"] / "fundamental_recoveries/synthetic/manifest.json").exists()
