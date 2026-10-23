"""Explicit, bounded statement collection and credential-free pinned replay.

Batch ledgers belong beside private snapshots, never in the public repository.
They are atomic checkpoints: an HTTP attempt is charged and marked in flight
*before* sending it. A process interruption therefore cannot silently repeat it.
No latest-snapshot/age selection, retry, provider switch or credential loading
occurs here. All collectors/readers must use a quiescent catalog; this module's
collection and replay entry points additionally coordinate through a root lock.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from . import fundamental_snapshots
from .alpha_vantage_rest import AlphaVantageError
from .fundamental_snapshots import FUNCTIONS, NORMALIZER, replay_fundamentals
from .offline_reader import OfflineDataReader
from .snapshot_store import SnapshotStore, utc_time

SCHEMA = "av_fundamental_batch_v1"
_LOCK = ".fundamental_batch.lock"
_PACING = "fundamental_batch_pacing.json"


def _body(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_body(value)).hexdigest()


def _normalized_manifest_sha(value):
    """Match the existing OfflineDataReader's complete manifest fingerprint."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _integer(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _run_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError("Invalid batch run identifier")
    return value


def _path(root, run_id):
    return Path(root) / "fundamental_batches" / _run_id(run_id) / "manifest.json"


@contextmanager
def _lock(root, *, readonly=False):
    """Fail promptly on an active batch writer/reader; do not wait indefinitely."""
    path = Path(root) / _LOCK
    with path.open("rb" if readonly else "a+b") as stream:
        try:
            fcntl.flock(stream, (fcntl.LOCK_SH if readonly else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Batch catalog is active; use a quiescent root") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(_body(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        with _directory(path.parent):
            pass
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)


def _save(root, manifest, now):
    manifest["updated_at"] = utc_time(now).isoformat()
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = _sha(manifest)
    _atomic(_path(root, manifest["run_id"]), manifest)


def _load(root, run_id):
    manifest = json.loads(_path(root, run_id).read_bytes())
    content = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != _sha(content) or manifest.get("schema") != SCHEMA or (
        manifest.get("run_id") != run_id or manifest.get("config_sha256") != _sha(manifest.get("config"))
    ):
        raise ValueError("Batch checkpoint fingerprint/schema mismatch")
    config = manifest["config"]
    expected = [{"function": function, "symbol": symbol} for symbol in config["symbols"] for function in FUNCTIONS]
    if [job["request"] for job in manifest["jobs"]] != expected or any(
        job["job_id"] != f"{job['request']['symbol']}:{job['request']['function']}"
        or job["status"] not in {"pending", "inflight", "succeeded", "failed", "uncertain"}
        or len(job["attempts"]) > config["max_attempts_per_job"] for job in manifest["jobs"]
    ) or sum(len(job["attempts"]) for job in manifest["jobs"]) > config["max_requests"]:
        raise ValueError("Batch checkpoint violates its fixed job/attempt budget")
    return manifest


def _pin(store, request, receipt):
    record = store.get(receipt["snapshot_id"])
    if record is None or record["provider"] != "alpha_vantage" or json.loads(record["request_json"]) != request:
        raise ValueError("Imported/pinned snapshot differs from the explicit request")
    if receipt.get("normalizer") != NORMALIZER or record["raw_sha256"] != receipt.get("raw_sha256"):
        raise ValueError("Imported/pinned raw or normalizer identity differs")
    if receipt.get("observed_at") != record["observed_at"]:
        raise ValueError("Imported/pinned observation time differs")
    # Import is selection of an already materialized successful observation.
    # Never normalize an absent import or substitute a more recent snapshot.
    existing = store.dataset(record["id"], NORMALIZER)
    if existing is None:
        raise ValueError("Imported/pinned materialization is missing")
    existing = replay_fundamentals(store, record)
    tables = {name: {key: table[key] for key in ("sha256", "rows")} for name, table in existing["tables"].items()}
    if {name: {key: table[key] for key in ("sha256", "rows")} for name, table in receipt["tables"].items()} != tables:
        raise ValueError("Imported/pinned table fingerprints differ")
    pin = {"snapshot_id": record["id"], "normalizer": NORMALIZER, "raw_sha256": record["raw_sha256"],
           "observed_at": record["observed_at"], "tables": tables,
           "normalized_manifest_sha256": _normalized_manifest_sha(existing)}
    if "normalized_manifest_sha256" in receipt and receipt["normalized_manifest_sha256"] != pin["normalized_manifest_sha256"]:
        raise ValueError("Pinned complete normalized manifest fingerprint differs")
    if "provenance" in receipt and receipt["provenance"] != existing["provenance"]:
        raise ValueError("Imported provenance differs from the stored materialization")
    if "pandas_version" in receipt and receipt["pandas_version"] != existing["pandas_version"]:
        raise ValueError("Imported materialization version differs")
    for name, table in receipt["tables"].items():
        if "path" in table and table != existing["tables"][name]:
            raise ValueError("Imported complete table manifest differs")
    return pin


def create_fundamental_batch(
    store: SnapshotStore, *, run_id: str, symbols: list[str], universe_sha256: str,
    max_requests: int, min_interval_seconds: float = 15.0, max_attempts_per_job: int = 1,
    import_receipts=(), refresh_of: str | None = None, universe_scope: str = "explicit_selection", clock=utc_time,
) -> dict:
    """Freeze a complete three-statement plan and its total attempt budget.

    Imports are explicit successful receipts, independent of observation age.
    max_requests counts every future HTTP attempt, including failures/uncertain
    sends; imports cost zero. Retry capacity must be authorized in this plan.
    An identical universe/selection needs refresh_of and a new run identifier.
    """
    _run_id(run_id)
    _integer(max_requests, "max_requests")
    _integer(max_attempts_per_job, "max_attempts_per_job", 1)
    if not isinstance(symbols, (list, tuple)) or not symbols or any(
        not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol) for symbol in symbols
    ) or len(set(symbols)) != len(symbols):
        raise ValueError("Require nonempty unique explicit provider symbols")
    if not isinstance(universe_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", universe_sha256):
        raise ValueError("Bind a frozen universe SHA256 fingerprint")
    if universe_scope not in {"explicit_selection", "exact_current_index", "etf_proxy", "secondary_index"}:
        raise ValueError("Declare the frozen universe scope without upgrading a proxy")
    if isinstance(min_interval_seconds, bool) or not isinstance(min_interval_seconds, (int, float)) or not (
        math.isfinite(min_interval_seconds) and 1 <= min_interval_seconds <= 3600
    ):
        raise ValueError("min_interval_seconds must be between 1 and 3600; choose it for the verified provider plan")
    if not isinstance(import_receipts, (list, tuple)):
        raise TypeError("Imports require an explicit receipt list")
    now = utc_time(clock())
    with _lock(store.root):
        if _path(store.root, run_id).exists():
            raise ValueError("Batch already exists; resume it or explicitly refresh into a new run")
        if refresh_of is not None:
            prior = _load(store.root, _run_id(refresh_of))
            if prior["config"]["universe_sha256"] != universe_sha256 or prior["config"]["symbols"] != list(symbols):
                raise ValueError("Refresh must retain the original frozen universe and selection")
            if import_receipts:
                raise ValueError("A refresh creates fresh observations; imports are not permitted")
        else:
            for path in (store.root / "fundamental_batches").glob("*/manifest.json"):
                prior = _load(store.root, path.parent.name)
                if prior["config"]["universe_sha256"] == universe_sha256 and prior["config"]["symbols"] == list(symbols):
                    raise ValueError("Selection already has a run; explicit refresh_of is required")
        jobs = [{"job_id": f"{symbol}:{function}", "request": {"function": function, "symbol": symbol},
                 "status": "pending", "imported": False, "pin": None, "attempts": []}
                for symbol in symbols for function in FUNCTIONS]
        selected = set()
        for receipt in import_receipts:
            request = receipt["request"]
            matches = [job for job in jobs if job["request"] == request]
            if len(matches) != 1 or matches[0]["job_id"] in selected:
                raise ValueError("Imported receipts must uniquely match declared jobs")
            job = matches[0]
            job.update(pin=_pin(store, request, receipt), status="succeeded", imported=True)
            if utc_time(job["pin"]["observed_at"]) > now:
                raise ValueError("Imported observation is later than the batch creation clock")
            selected.add(job["job_id"])
        required = sum(job["status"] == "pending" for job in jobs)
        if required > max_requests:
            raise ValueError(f"Plan needs {required} first attempts, exceeding total budget {max_requests}")
        config = {"symbols": list(symbols), "functions": list(FUNCTIONS), "universe_sha256": universe_sha256,
                  "universe_scope": universe_scope,
                  "max_requests": max_requests, "max_attempts_per_job": max_attempts_per_job,
                  "min_interval_seconds": min_interval_seconds, "normalizer": NORMALIZER,
                  "import_receipts_sha256": _sha(list(import_receipts)),
                  "normalizer_source_sha256": hashlib.sha256(Path(fundamental_snapshots.__file__).read_bytes()).hexdigest(),
                  "collector_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        manifest = {"schema": SCHEMA, "run_id": run_id, "created_at": now.isoformat(), "config": config,
                    "config_sha256": _sha(config), "refresh_of": refresh_of, "jobs": jobs,
                    "state": "complete" if required == 0 else "ready", "halt_reason": None, "halts": []}
        _save(store.root, manifest, now)
        return deepcopy(manifest)


def _classify(kind):
    if not isinstance(kind, str):
        return "safety", True
    if kind in {"http_401", "http_403", "authentication", "auth"}:
        return "authentication", True
    if kind in {"http_429", "quota", "rate_limit"}:
        return "quota", True
    if kind == "provider_notice_or_error":
        # Existing sanitized adapter deliberately does not retain provider text.
        # The notice can mean quota/auth/entitlement, so halt conservatively.
        return "provider_notice_or_error", True
    if kind == "credential_echo":
        return "safety", True
    if kind == "transport":
        return "transport", False
    if kind.startswith("http_"):
        return "http", False
    if kind in {"invalid_json", "invalid_or_empty_json"}:
        return "response_format", False
    return "safety", True


def run_fundamental_batch(
    client, store: SnapshotStore, *, run_id: str, max_requests: int,
    retry_jobs=(), resume_after_halt: bool = False, clock=utc_time, sleep=time.sleep,
) -> dict:
    """Send at most the per-call budget and never exceed the frozen run budget.

    Resume selects pending jobs only. Failed/uncertain jobs require explicit
    retry_jobs, reserved per-job capacity and remaining run budget. Clearing a
    quota/auth/safety halt additionally requires resume_after_halt=True.
    """
    _integer(max_requests, "max_requests")
    if not isinstance(resume_after_halt, bool) or not isinstance(retry_jobs, (list, tuple)) or any(
        not isinstance(job, str) for job in retry_jobs
    ) or len(set(retry_jobs)) != len(retry_jobs):
        raise ValueError("Declare unique explicit retries and a boolean halt acknowledgment")
    with _lock(store.root):
        manifest = _load(store.root, _run_id(run_id))
        config = manifest["config"]
        if config["collector_source_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest() or (
            config["normalizer_source_sha256"] != hashlib.sha256(Path(fundamental_snapshots.__file__).read_bytes()).hexdigest()
        ):
            raise ValueError("Pinned collector/normalizer source changed; use the original code version")
        # Reconcile lost workers before considering any new send. In-flight
        # attempts were already charged even if the provider never received one.
        for job in manifest["jobs"]:
            if job["status"] == "inflight":
                job["status"] = "uncertain"
                job["attempts"][-1].update(status="uncertain", error_category="interrupted_inflight")
            if job["status"] == "succeeded":
                _pin(store, job["request"], job["pin"])
        _save(store.root, manifest, clock())
        if manifest["halt_reason"] and not resume_after_halt:
            return deepcopy(manifest)
        selected = {job["job_id"]: job for job in manifest["jobs"]}
        for job_id in retry_jobs:
            if job_id not in selected or selected[job_id]["status"] not in {"failed", "uncertain"}:
                raise ValueError("Explicit retry must identify an existing failed/uncertain job")
            if len(selected[job_id]["attempts"]) >= config["max_attempts_per_job"]:
                raise ValueError("Explicit retry exceeds the frozen per-job attempt budget")
        jobs = [job for job in manifest["jobs"] if job["status"] == "pending" or job["job_id"] in retry_jobs]
        used = sum(len(job["attempts"]) for job in manifest["jobs"])
        allowed = min(max_requests, config["max_requests"] - used)
        if jobs and allowed and client is None:
            raise ValueError("Collection needs an explicitly supplied client; use pinned replay offline")
        manifest["halt_reason"] = None
        for job in jobs[:allowed]:
            pacing_path = store.root / _PACING
            pacing = json.loads(pacing_path.read_bytes()) if pacing_path.exists() else {}
            now = utc_time(clock())
            if pacing.get("last_request_started_at"):
                previous = utc_time(pacing["last_request_started_at"])
                if now < previous:
                    raise ValueError("Collection clock moved backwards; pacing cannot be established safely")
                remaining = config["min_interval_seconds"] - (now - previous).total_seconds()
                if remaining > 0:
                    sleep(remaining)
                    now = utc_time(clock())
                    if now < previous + timedelta(seconds=config["min_interval_seconds"]):
                        raise ValueError("Sleep/clock did not satisfy the persisted request interval")
            attempt = {"number": len(job["attempts"]) + 1, "status": "inflight",
                       "request_started_at": now.isoformat(), "response_received_at": None, "error_category": None}
            job["attempts"].append(attempt)
            job["status"] = "inflight"
            manifest["state"] = "running"
            # Pacing is persisted first: a crash can delay a future request but
            # cannot erase the spacing reservation for a request already sent.
            _atomic(pacing_path, {"last_request_started_at": now.isoformat()})
            _save(store.root, manifest, now)
            halt = False
            try:
                response = client.fetch_json_response(job["request"]["function"], {"symbol": job["request"]["symbol"]})
                received = utc_time(clock())
                if received < now:
                    raise ValueError("Response clock precedes request")
                attempt["response_received_at"] = received.isoformat()
            except AlphaVantageError as exc:
                category, halt = _classify(exc.kind)
                attempt.update(status="failed", response_received_at=utc_time(clock()).isoformat(), error_category=category)
                job["status"] = "failed"
            except (KeyboardInterrupt, SystemExit):
                attempt.update(status="uncertain", error_category="interrupted_inflight")
                job["status"] = "uncertain"
                manifest["state"] = "incomplete"
                _save(store.root, manifest, clock())
                raise
            except Exception:  # noqa: BLE001 - sanitize arbitrary adapter errors before persisting a halt
                # Never persist exception text: custom adapters can include
                # credential-bearing URLs or response bodies in exceptions.
                attempt.update(status="uncertain", error_category="safety")
                job["status"], halt = "uncertain", True
            else:
                try:
                    record = store.capture("alpha_vantage", job["request"], response.body, observed_at=received)
                    attempt.update(snapshot_id=record["id"], raw_sha256=record["raw_sha256"])
                except Exception:  # noqa: BLE001 - storage/source errors must not expose response bodies
                    attempt.update(status="failed", error_category="safety")
                    job["status"], halt = "failed", True
                else:
                    try:
                        normalized = replay_fundamentals(store, record)
                    except ValueError:
                        # Keep the immutable raw capture for investigation.
                        attempt.update(status="failed", error_category="data_quality")
                        job["status"] = "failed"
                    except Exception:  # noqa: BLE001 - retain charged attempts and halt on unexpected storage errors
                        attempt.update(status="failed", error_category="storage_or_safety")
                        job["status"], halt = "failed", True
                    else:
                        job.update(status="succeeded", pin=_pin(store, job["request"], normalized))
                        attempt["status"] = "succeeded"
            if halt:
                manifest["halt_reason"] = attempt["error_category"]
                manifest["halts"].append({"job_id": job["job_id"], "category": attempt["error_category"],
                                          "at": utc_time(clock()).isoformat()})
                manifest["state"] = "halted"
            _save(store.root, manifest, clock())
            if halt:
                break
        if not manifest["halt_reason"]:
            manifest["state"] = "complete" if all(job["status"] == "succeeded" for job in manifest["jobs"]) else "incomplete"
            _save(store.root, manifest, clock())
        return deepcopy(manifest)


def read_fundamental_batch(data_root, *, run_id: str) -> dict:
    """Read the private pinned ledger without opening/creating a SnapshotStore."""
    with _lock(data_root, readonly=True):
        return _load(data_root, _run_id(run_id))


def fundamental_batch_summary(manifest: dict) -> dict:
    """Publishable aggregates/fingerprints; no local paths or source object IDs."""
    jobs = manifest["jobs"]
    counts = {status: sum(job["status"] == status for job in jobs)
              for status in ("pending", "inflight", "succeeded", "failed", "uncertain")}
    attempts = [attempt for job in jobs for attempt in job["attempts"]]
    categories = sorted({attempt["error_category"] for attempt in attempts if attempt["error_category"]})
    return {"schema": SCHEMA, "state": manifest["state"], "universe_sha256": manifest["config"]["universe_sha256"],
            "universe_scope": manifest["config"]["universe_scope"],
            "config_sha256": manifest["config_sha256"], "manifest_sha256": manifest["manifest_sha256"],
            "input_sha256": _sha([job["pin"] for job in jobs if job["pin"]]),
            "symbols": len(manifest["config"]["symbols"]), "planned_jobs": len(jobs), "coverage": counts,
            "imported_jobs": sum(job["imported"] for job in jobs), "attempts_used": len(attempts),
            "max_requests": manifest["config"]["max_requests"],
            "remaining_request_budget": manifest["config"]["max_requests"] - len(attempts),
            "failure_categories": {category: sum(attempt["error_category"] == category for attempt in attempts)
                                   for category in categories}, "halt_reason": manifest["halt_reason"],
            "timing_status": "current_snapshot_only_historical_availability_unverified"}


def replay_fundamental_batch(data_root, *, run_id: str) -> dict:
    """Verify/read all successful pinned tables; never fetch, normalize or write.

    Missing/failed/uncertain jobs stay visible through coverage. Replay does not
    certify historical availability, provider unit scale or security identity.
    """
    with _lock(data_root, readonly=True):
        manifest = _load(data_root, _run_id(run_id))
        reader = OfflineDataReader(data_root)
        rows, tables = 0, 0
        for job in manifest["jobs"]:
            if job["status"] != "succeeded":
                continue
            pin = job["pin"]
            catalog = reader.catalog(provider="alpha_vantage", request=job["request"])
            expected = {name: item for name, item in pin["tables"].items()}
            chosen = {item["table"]: item for item in catalog
                      if item["snapshot_id"] == pin["snapshot_id"] and item["normalizer"] == pin["normalizer"]}
            if set(chosen) != set(expected) or any(
                chosen[name]["raw_sha256"] != pin["raw_sha256"]
                or chosen[name]["observed_at"] != pin["observed_at"]
                or chosen[name]["table_sha256"] != item["sha256"] or chosen[name]["rows"] != item["rows"]
                for name, item in expected.items()
            ):
                raise ValueError("Pinned offline catalog differs from the batch receipt")
            for name in expected:
                result = reader.read(snapshot_id=pin["snapshot_id"], normalizer=pin["normalizer"], table=name)
                if result.metadata["manifest_sha256"] != pin["normalized_manifest_sha256"] or (
                    result.metadata["observed_at"] != pin["observed_at"]
                ):
                    raise ValueError("Pinned complete normalized manifest/observation differs during offline replay")
                rows += len(result.frame)
                tables += 1
        return {**fundamental_batch_summary(manifest), "replayed_tables": tables, "replayed_rows": rows,
                "access_mode": "offline_read_only"}
