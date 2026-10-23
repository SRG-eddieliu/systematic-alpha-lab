"""Failure/restart/budget tests use synthetic statements and never a network."""
import fcntl
import hashlib
import importlib.util
import json
import socket
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from systematic_alpha_lab.data_pipeline.alpha_vantage_rest import AlphaVantageError, JSONResponse
from systematic_alpha_lab.data_pipeline.fundamental_batch import (
    create_fundamental_batch,
    fundamental_batch_summary,
    read_fundamental_batch,
    replay_fundamental_batch,
    run_fundamental_batch,
)
from systematic_alpha_lab.data_pipeline.fundamental_snapshots import FUNCTIONS, replay_fundamentals
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)
UNIVERSE = "d" * 64


class Clock:
    def __init__(self):
        self.now, self.sleeps = NOW, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


class Feed:
    def __init__(self, clock, outcomes=()):
        self.clock, self.outcomes, self.calls = clock, list(outcomes), []

    def fetch_json_response(self, function, params):
        self.calls.append((function, params, self.clock()))
        self.clock.now += timedelta(seconds=1)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome
        content = outcome or payload(params["symbol"])
        return JSONResponse(content, json.dumps(content).encode())


def payload(symbol="SYNTH"):
    return {"symbol": symbol,
            "annualReports": [{"fiscalDateEnding": "2025-12-31", "reportedCurrency": "USD", "netIncome": "100"}],
            "quarterlyReports": [{"fiscalDateEnding": "2026-03-31", "reportedCurrency": "USD", "netIncome": "25"}]}


def create(store, clock, **kwargs):
    return create_fundamental_batch(store, run_id="test", symbols=["SYNTH"], universe_sha256=UNIVERSE,
                                    max_requests=kwargs.pop("max_requests", 3), clock=clock, **kwargs)


def run(feed, store, clock, **kwargs):
    return run_fundamental_batch(feed, store, run_id="test", max_requests=kwargs.pop("max_requests", 3),
                                 clock=clock, sleep=clock.sleep, **kwargs)


def receipt(store, function=FUNCTIONS[0]):
    request = {"symbol": "SYNTH", "function": function}
    record = store.capture("alpha_vantage", request, json.dumps(payload()).encode(), observed_at=NOW)
    return {"request": request, "cache_hit": False, **replay_fundamentals(store, record)}


def files(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_full_plan_budget_is_checked_before_creation(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    with pytest.raises(ValueError, match="needs 3 first attempts"):
        create(store, clock, max_requests=2)
    assert not (tmp_path / "fundamental_batches/test/manifest.json").exists()


def test_successful_jobs_are_pinned_and_never_refetched_on_resume(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    feed = Feed(clock)
    first = run(feed, store, clock, max_requests=1)
    assert first["jobs"][0]["status"] == "succeeded"
    assert first["jobs"][0]["attempts"][0]["request_started_at"] == NOW.isoformat()
    assert first["jobs"][0]["attempts"][0]["response_received_at"] == (NOW + timedelta(seconds=1)).isoformat()
    second = run(feed, store, clock)
    assert len(feed.calls) == 3 and second["state"] == "complete"
    pinned = first["jobs"][0]["pin"]
    assert second["jobs"][0]["pin"] == pinned
    # An unrelated newer observation cannot affect exact successful pins.
    later = receipt(store)
    assert later["snapshot_id"] != pinned["snapshot_id"]
    completed = run(None, store, clock)
    assert completed["jobs"][0]["pin"] == pinned
    assert fundamental_batch_summary(completed)["attempts_used"] == 3


def test_explicit_imports_reuse_all_old_observations_without_requests(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    imports = [receipt(store, function) for function in FUNCTIONS]
    clock.now += timedelta(days=180)
    manifest = create(store, clock, max_requests=0, import_receipts=imports)
    assert manifest["state"] == "complete"
    result = run(None, store, clock, max_requests=0)
    assert [job["pin"]["snapshot_id"] for job in result["jobs"]] == [item["snapshot_id"] for item in imports]
    assert fundamental_batch_summary(result)["imported_jobs"] == 3
    assert not (tmp_path / "fundamental_batch_pacing.json").exists()


@pytest.mark.parametrize("change", ["request", "raw", "table", "time", "duplicate", "missing"])
def test_imported_receipts_are_verified_before_a_plan_is_published(tmp_path, change):
    store, clock = SnapshotStore(tmp_path), Clock()
    imported = receipt(store)
    if change == "request": imported["request"]["symbol"] = "OTHER"
    if change == "raw": imported["raw_sha256"] = "0" * 64
    if change == "table": imported["tables"]["annual"]["sha256"] = "0" * 64
    if change == "time": imported["observed_at"] = "2020-01-01T00:00:00+00:00"
    if change == "missing": imported["snapshot_id"] = "0" * 32
    imports = [imported, imported] if change == "duplicate" else [imported]
    with pytest.raises(ValueError):
        create(store, clock, import_receipts=imports)
    assert not (tmp_path / "fundamental_batches/test/manifest.json").exists()


def test_persisted_interval_survives_restart_and_applies_to_refresh_runs(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    feed = Feed(clock)
    run(feed, store, clock, max_requests=1)
    # Reconstruct every caller-owned object after a short process interruption.
    store = SnapshotStore(tmp_path)
    run(feed, store, clock, max_requests=1)
    assert clock.sleeps == [14.0]
    create_fundamental_batch(store, run_id="refresh", symbols=["SYNTH"], universe_sha256=UNIVERSE,
                              max_requests=3, refresh_of="test", clock=clock)
    run_fundamental_batch(feed, store, run_id="refresh", max_requests=1, clock=clock, sleep=clock.sleep)
    assert [item[2] for item in feed.calls] == [NOW, NOW + timedelta(seconds=15), NOW + timedelta(seconds=30)]


@pytest.mark.parametrize("kind,category", [
    ("provider_notice_or_error", "provider_notice_or_error"), ("http_429", "quota"),
    ("http_401", "authentication"), ("http_403", "authentication"), ("credential_echo", "safety"),
])
def test_quota_auth_and_safety_halt_before_the_next_job(tmp_path, kind, category):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    feed = Feed(clock, [AlphaVantageError(kind)])
    first = run(feed, store, clock)
    assert len(feed.calls) == 1 and first["state"] == "halted"
    assert first["halt_reason"] == category
    assert fundamental_batch_summary(first)["attempts_used"] == 1
    second = run(feed, store, clock)
    assert len(feed.calls) == 1 and second["state"] == "halted"
    acknowledged = run(feed, store, clock, resume_after_halt=True)
    assert len(feed.calls) == 3 and acknowledged["jobs"][0]["status"] == "failed"
    assert acknowledged["state"] == "incomplete"


def test_failed_requests_count_toward_run_and_call_budgets_without_auto_retry(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    feed = Feed(clock, [AlphaVantageError("transport")])
    first = run(feed, store, clock, max_requests=1)
    assert len(feed.calls) == 1 and first["jobs"][0]["status"] == "failed"
    final = run(feed, store, clock, max_requests=999)
    assert len(feed.calls) == 3 and final["jobs"][0]["status"] == "failed"
    assert fundamental_batch_summary(final)["remaining_request_budget"] == 0
    with pytest.raises(ValueError, match="per-job attempt budget"):
        run(feed, store, clock, retry_jobs=["SYNTH:INCOME_STATEMENT"])
    assert len(feed.calls) == 3


def test_manual_retry_is_explicit_bounded_and_retains_failure_receipts(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock, max_requests=4, max_attempts_per_job=2)
    feed = Feed(clock, [AlphaVantageError("transport")])
    run(feed, store, clock)
    first = run(feed, store, clock)
    assert len(feed.calls) == 3 and first["state"] == "incomplete"
    final = run(feed, store, clock, retry_jobs=["SYNTH:INCOME_STATEMENT"])
    assert len(feed.calls) == 4 and final["state"] == "complete"
    attempts = final["jobs"][0]["attempts"]
    assert [item["status"] for item in attempts] == ["failed", "succeeded"]
    assert final["jobs"][0]["pin"]["snapshot_id"] == attempts[-1]["snapshot_id"]


def test_keyboard_interrupt_marks_uncertain_and_does_not_resend_on_resume(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock, max_requests=4, max_attempts_per_job=2)
    feed = Feed(clock, [KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        run(feed, store, clock)
    ledger = read_fundamental_batch(tmp_path, run_id="test")
    assert ledger["jobs"][0]["status"] == "uncertain"
    resumed = run(feed, store, clock)
    assert len(feed.calls) == 3 and resumed["jobs"][0]["status"] == "uncertain"
    retried = run(feed, store, clock, retry_jobs=["SYNTH:INCOME_STATEMENT"])
    assert len(feed.calls) == 4 and retried["state"] == "complete"


def test_lost_worker_inflight_checkpoint_is_reconciled_to_uncertain(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    feed = Feed(clock)
    original_save = __import__("systematic_alpha_lab.data_pipeline.fundamental_batch", fromlist=["_save"])._save

    def terminate_after_reserved(root, manifest, now):
        original_save(root, manifest, now)
        if manifest["jobs"][0]["status"] == "inflight":
            raise SystemExit()

    from unittest.mock import patch
    with patch("systematic_alpha_lab.data_pipeline.fundamental_batch._save", side_effect=terminate_after_reserved), pytest.raises(SystemExit):
        run(feed, store, clock)
    assert not feed.calls
    assert read_fundamental_batch(tmp_path, run_id="test")["jobs"][0]["status"] == "inflight"
    result = run(feed, store, clock)
    assert len(feed.calls) == 2 and result["jobs"][0]["status"] == "uncertain"
    assert fundamental_batch_summary(result)["attempts_used"] == 3


def test_invalid_statement_is_raw_only_and_other_jobs_continue(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    invalid = payload()
    invalid["quarterlyReports"][0]["reportedCurrency"] = "None"
    feed = Feed(clock, [invalid])
    result = run(feed, store, clock)
    assert len(feed.calls) == 3
    assert [job["status"] for job in result["jobs"]] == ["failed", "succeeded", "succeeded"]
    attempt = result["jobs"][0]["attempts"][0]
    assert attempt["error_category"] == "data_quality"
    record = store.get(attempt["snapshot_id"])
    assert store.read_payload(record) == invalid
    assert store.dataset(record["id"], "av_fundamentals_v1") is None


def test_unexpected_errors_never_leak_adapter_exception_text(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    feed = Feed(clock, [RuntimeError("private-credential-sentinel https://source.invalid/?apikey=sentinel")])
    result = run(feed, store, clock)
    assert result["state"] == "halted" and len(feed.calls) == 1
    assert b"sentinel" not in (tmp_path / "fundamental_batches/test/manifest.json").read_bytes()


def test_refresh_requires_new_run_and_does_not_replace_old_pins(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    first = run(Feed(clock), store, clock)
    with pytest.raises(ValueError, match="already exists"):
        create(store, clock)
    with pytest.raises(ValueError, match="explicit refresh_of"):
        create_fundamental_batch(store, run_id="accidental", symbols=["SYNTH"], universe_sha256=UNIVERSE,
                                  max_requests=3, clock=clock)
    create_fundamental_batch(store, run_id="refresh", symbols=["SYNTH"], universe_sha256=UNIVERSE,
                              max_requests=3, refresh_of="test", clock=clock)
    second = run_fundamental_batch(Feed(clock), store, run_id="refresh", max_requests=3, clock=clock, sleep=clock.sleep)
    assert {job["pin"]["snapshot_id"] for job in first["jobs"]}.isdisjoint(
        {job["pin"]["snapshot_id"] for job in second["jobs"]})
    assert read_fundamental_batch(tmp_path, run_id="test")["jobs"] == first["jobs"]


def test_reordered_identical_selection_cannot_bypass_explicit_refresh(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create_fundamental_batch(store, run_id="original", symbols=["AAA", "BBB"], universe_sha256=UNIVERSE,
                              max_requests=6, clock=clock)
    with pytest.raises(ValueError, match="explicit refresh_of"):
        create_fundamental_batch(store, run_id="reordered", symbols=["BBB", "AAA"], universe_sha256=UNIVERSE,
                                  max_requests=6, clock=clock)


def test_explicit_refresh_accepts_reordered_same_selection_without_rewriting_original(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    original = create_fundamental_batch(store, run_id="original", symbols=["AAA", "BBB"], universe_sha256=UNIVERSE,
                                         max_requests=6, clock=clock)
    refreshed = create_fundamental_batch(store, run_id="reordered", symbols=["BBB", "AAA"], universe_sha256=UNIVERSE,
                                          max_requests=6, refresh_of="original", clock=clock)
    assert original["config"]["symbols"] == ["AAA", "BBB"]
    assert refreshed["config"]["symbols"] == ["BBB", "AAA"]
    assert read_fundamental_batch(tmp_path, run_id="original") == original


def test_offline_replay_blocks_network_and_preserves_all_bytes_and_mtimes(tmp_path, monkeypatch):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    run(Feed(clock), store, clock)
    before = files(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline replay attempted a network connection")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    result = replay_fundamental_batch(tmp_path, run_id="test")
    assert result["replayed_tables"] == 6 and result["replayed_rows"] == 6
    assert result["access_mode"] == "offline_read_only" and result["state"] == "complete"
    assert files(tmp_path) == before


def test_old_collector_code_pin_stays_immutable_and_can_replay_after_code_upgrade(tmp_path, monkeypatch):
    import systematic_alpha_lab.data_pipeline.fundamental_batch as batch_module

    prior_source = tmp_path / "prior_collector.py"
    prior_source.write_text("# Synthetic prior collector source version for code-pin compatibility testing\n")
    store, clock = SnapshotStore(tmp_path / "data"), Clock()
    with monkeypatch.context() as original_version:
        original_version.setattr(batch_module, "__file__", str(prior_source))
        create(store, clock)
        original = run(Feed(clock), store, clock)
    before = files(store.root)
    result = replay_fundamental_batch(store.root, run_id="test")
    assert result["state"] == "complete" and result["replayed_tables"] == 6
    assert read_fundamental_batch(store.root, run_id="test") == original
    assert files(store.root) == before
    with pytest.raises(ValueError, match="collector/normalizer source changed"):
        run(None, store, clock)
    assert files(store.root) == before


def test_replay_cli_does_not_load_credentials_or_create_a_writable_store(tmp_path, monkeypatch, capsys):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    run(Feed(clock), store, clock)
    before = files(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay attempted credential/store/network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr("systematic_alpha_lab.data_pipeline.config_loader.load_credentials", forbidden)
    monkeypatch.setattr(SnapshotStore, "__init__", forbidden)
    monkeypatch.setattr("sys.argv", ["collect_fundamental_batch.py", "replay", "--data-root", str(tmp_path), "--run-id", "test"])
    spec = importlib.util.spec_from_file_location("batch_cli", Path(__file__).parents[1] / "examples/collect_fundamental_batch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result["access_mode"] == "offline_read_only"
    assert files(tmp_path) == before


def test_corruption_is_rejected_before_resume_or_offline_replay(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    feed = Feed(clock)
    result = run(feed, store, clock, max_requests=1)
    record = store.get(result["jobs"][0]["pin"]["snapshot_id"])
    (tmp_path / record["raw_path"]).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        run(feed, store, clock)
    assert len(feed.calls) == 1
    with pytest.raises(ValueError, match="hash mismatch"):
        replay_fundamental_batch(tmp_path, run_id="test")


def test_root_lock_prevents_overlapping_batch_collection_and_replay(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    feed = Feed(clock)
    with (tmp_path / ".fundamental_batch.lock").open("rb") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="active"):
            run(feed, store, clock)
        with pytest.raises(ValueError, match="active"):
            replay_fundamental_batch(tmp_path, run_id="test")
    assert not feed.calls


def test_checkpoint_tampering_is_rejected_before_requests(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    path = tmp_path / "fundamental_batches/test/manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["config"]["max_requests"] = 100
    path.write_text(json.dumps(manifest))
    feed = Feed(clock)
    with pytest.raises(ValueError, match="fingerprint"):
        run(feed, store, clock)
    assert not feed.calls


def test_replay_rejects_changed_provenance_even_when_raw_and_tables_still_match(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    ledger = run(Feed(clock), store, clock)
    pin = ledger["jobs"][0]["pin"]
    with sqlite3.connect(store.catalog) as db:
        row = db.execute("SELECT manifest_json FROM datasets WHERE snapshot_id=? AND normalizer=?",
                         (pin["snapshot_id"], pin["normalizer"])).fetchone()
        normalized = json.loads(row[0])
        normalized["provenance"]["additional_claim"] = "changed without changing the source bytes"
        db.execute("UPDATE datasets SET manifest_json=? WHERE snapshot_id=? AND normalizer=?",
                   (json.dumps(normalized), pin["snapshot_id"], pin["normalizer"]))
    with pytest.raises(ValueError, match="complete normalized manifest"):
        replay_fundamental_batch(tmp_path, run_id="test")


def test_public_summary_has_no_private_paths_or_raw_source_identifiers(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    create(store, clock)
    manifest = run(Feed(clock), store, clock)
    summary = json.dumps(fundamental_batch_summary(manifest))
    assert str(tmp_path) not in summary and "snapshot_id" not in summary
    assert all(job["pin"]["snapshot_id"] not in summary for job in manifest["jobs"])


def test_explicit_interval_and_proxy_scope_are_pinned_without_upgrading_scope(tmp_path):
    store, clock = SnapshotStore(tmp_path), Clock()
    manifest = create(store, clock, min_interval_seconds=1.1, universe_scope="etf_proxy")
    result = run(Feed(clock), store, clock)
    assert result["config_sha256"] == manifest["config_sha256"]
    assert clock.sleeps == pytest.approx([0.1, 0.1])
    assert fundamental_batch_summary(result)["universe_scope"] == "etf_proxy"


@pytest.mark.parametrize("flags,accepted", [
    ([], False), (["--allow-proxy"], False), (["--allow-unverified-mappings"], False),
    (["--allow-proxy", "--allow-unverified-mappings"], True),
])
def test_cli_requires_separate_proxy_and_unverified_mapping_opt_ins(tmp_path, monkeypatch, capsys, flags, accepted):
    from systematic_alpha_lab.data_pipeline.universe import freeze_universe, write_universe

    universe = freeze_universe([{
        "security_id": "synthetic-security", "company_id": None, "company_name": None,
        "security_name": "Synthetic security", "source_symbol": "SYNTH", "provider": "alpha_vantage",
        "provider_symbol": "SYNTH", "provider_symbol_status": "unverified", "mapping_evidence": [],
    }], {
        "source_url": "https://example.org/synthetic-holdings", "captured_at": NOW.isoformat(),
        "as_of": "2026-10-22", "raw_sha256": "a" * 64, "kind": "etf_proxy", "source_status": "current",
        "verification": {"status": "unverified", "scope": "unverified", "method": None, "evidence_urls": []},
    })
    source = tmp_path / "universe.json"
    write_universe(universe, source)

    def forbidden(*args, **kwargs):
        raise AssertionError("Plan attempted network or credential access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr("systematic_alpha_lab.data_pipeline.config_loader.load_credentials", forbidden)
    monkeypatch.setattr("sys.argv", ["collect_fundamental_batch.py", "plan", "--data-root", str(tmp_path / "data"),
                                    "--run-id", "proxy", "--universe", str(source), "--max-total-requests", "3", *flags])
    spec = importlib.util.spec_from_file_location("batch_cli", Path(__file__).parents[1] / "examples/collect_fundamental_batch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if accepted:
        module.main()
        result = json.loads(capsys.readouterr().out)
        assert result["universe_scope"] == "etf_proxy"
        assert result["universe"]["mapping_status_counts"]["unverified"] == 1
    else:
        with pytest.raises(SystemExit) as failure:
            module.main()
        assert failure.value.code == 1
        assert not (tmp_path / "data/fundamental_batches/proxy/manifest.json").exists()


@pytest.mark.parametrize("kwargs", [
    {"max_requests": True}, {"max_requests": -1}, {"max_attempts_per_job": 0},
    {"min_interval_seconds": 0}, {"min_interval_seconds": float("inf")},
])
def test_invalid_budget_or_interval_never_creates_a_plan(tmp_path, kwargs):
    with pytest.raises(ValueError):
        create(SnapshotStore(tmp_path), Clock(), **kwargs)
    assert not (tmp_path / "fundamental_batches/test/manifest.json").exists()
