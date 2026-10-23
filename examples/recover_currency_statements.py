"""Recover exact failed statement captures in a new, independent private copy.

No credentials, downloads, latest-version selection or changes to the source
batch are permitted. The source batch lock remains shared from the first
inventory until the final unchanged-source check. Other collectors must use the
same lock protocol. A failed operation may leave a partial output directory;
inspect it separately and choose a new output directory for another attempt.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

from systematic_alpha_lab.data_pipeline.fundamental_batch import read_fundamental_batch
from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.data_pipeline.universe import load_universe

SCHEMA = "av_currency_recovery_run_v1"
LOCK = ".fundamental_batch.lock"


def _body(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_body(value)).hexdigest()


def _manifest_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


@contextmanager
def _root_lock(root, *, shared):
    if (root / LOCK).is_symlink() or not stat.S_ISREG((root / LOCK).lstat().st_mode):
        raise ValueError("Batch lock must be an existing regular file, not a symlink")
    with (root / LOCK).open("rb") as stream:
        try:
            fcntl.flock(stream, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Catalog is active; use a closed source and independent output") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def inventory(root):
    """Fingerprint all regular files/directories without opening SQLite."""
    entries = []
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("Source/copy contains a symlink or special filesystem object")
        if path.name.endswith(("-journal", "-wal", "-shm")):
            raise ValueError("SQLite journal sidecars require a closed checkpoint before copying")
        entry = {"path": str(path.relative_to(root)), "kind": "directory" if path.is_dir() else "file",
                 "mtime_ns": info.st_mtime_ns, "mode": stat.S_IMODE(info.st_mode)}
        if path.is_file():
            entry.update(size=info.st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        entries.append(entry)
    return entries


def _safe_file(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("Snapshot object is outside the copied root")
    resolved = (root / path).resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("Snapshot object is outside the copied root")
    return resolved


def _verify_receipt(reader, receipt):
    if not isinstance(receipt.get("tables"), dict) or not receipt["tables"]:
        raise ValueError("Exact receipt requires a nonempty complete table set")
    stored = [item for item in reader.catalog(provider="alpha_vantage", request=receipt["request"])
              if item["snapshot_id"] == receipt["snapshot_id"] and item["normalizer"] == receipt["normalizer"]]
    if len(stored) != len(receipt["tables"]) or {item["table"] for item in stored} != set(receipt["tables"]):
        raise ValueError("Exact receipt does not contain the complete stored table set")
    for name, expected in receipt["tables"].items():
        result = reader.read(snapshot_id=receipt["snapshot_id"], normalizer=receipt["normalizer"], table=name)
        metadata = result.metadata
        if (metadata["request"] != receipt["request"] or metadata["raw_sha256"] != receipt["raw_sha256"]
                or metadata["observed_at"] != receipt["observed_at"]
                or metadata["manifest_sha256"] != receipt["normalized_manifest_sha256"]
                or metadata["table_sha256"] != expected["sha256"] or len(result.frame) != expected["rows"]):
            raise ValueError("Exact receipt differs from the copied offline dataset")


def _write_json(path, value):
    body = _body(value) + b"\n"
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(body).hexdigest()


def _record_for_attempt(store, job, attempt):
    if (not re.fullmatch(r"[0-9a-f]{32}", attempt.get("snapshot_id", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", attempt.get("raw_sha256", ""))):
        raise ValueError("A selected failed attempt lacks exact raw pins")
    record = store.get(attempt["snapshot_id"])
    if (record is None or record["provider"] != "alpha_vantage"
            or json.loads(record["request_json"]) != job["request"]
            or record["raw_sha256"] != attempt["raw_sha256"]
            or record["observed_at"] != attempt["response_received_at"]
            or record["request_id"] != SnapshotStore.request_id("alpha_vantage", job["request"])):
        raise ValueError("Failed-attempt raw pins differ from the copied catalog")
    body = _safe_file(store.root, record["raw_path"]).read_bytes()
    if hashlib.sha256(body).hexdigest() != attempt["raw_sha256"]:
        raise ValueError("Failed-attempt raw bytes differ from their pinned hash")
    return record


def recover(*, source_root, output_root, run_id, universe, code_commit):
    """Create a new recovery copy and return only publishable aggregates."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid explicit source batch identifier")
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", code_commit):
        raise ValueError("Supply the complete explicit code commit")
    requested_source, requested_universe = Path(source_root), Path(universe)
    if requested_source.is_symlink() or requested_universe.is_symlink():
        raise ValueError("Source root and universe must not be symlinks")
    source = requested_source.resolve(strict=True)
    output = Path(output_root).resolve()
    universe_path = requested_universe.resolve(strict=True)
    if not source.is_dir() or not universe_path.is_file():
        raise ValueError("Require an existing source root and frozen universe file")
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Source and output roots must not overlap")
    if Path(output_root).exists() or Path(output_root).is_symlink() or output.exists():
        raise ValueError("Recovery output must be a new directory")
    if not output.parent.is_dir():
        raise ValueError("The output parent must already exist")
    recovery_relative = Path("fundamental_recoveries") / run_id
    if (source / recovery_relative).exists():
        raise ValueError("Source already contains this recovery; choose its original closed baseline")

    from systematic_alpha_lab.data_pipeline import fundamental_recovery, fundamental_snapshots

    with _root_lock(source, shared=True):
        before = inventory(source)
        parent = read_fundamental_batch(source, run_id=run_id)
        if any(job["status"] in {"pending", "inflight", "uncertain"} for job in parent["jobs"]):
            raise ValueError("Source batch must have only terminal successful/failed jobs")
        universe_before = (universe_path.stat().st_mtime_ns, hashlib.sha256(universe_path.read_bytes()).hexdigest())
        frozen = load_universe(universe_path)
        if universe_before != (
            universe_path.stat().st_mtime_ns, hashlib.sha256(universe_path.read_bytes()).hexdigest()
        ):
            raise ValueError("Frozen universe changed while validating")
        if frozen["manifest_sha256"] != parent["config"]["universe_sha256"]:
            raise ValueError("Frozen universe differs from the complete source batch")
        shutil.copytree(source, output, copy_function=shutil.copy2, symlinks=False)
        if inventory(output) != before or inventory(source) != before:
            raise ValueError("Source changed or its independent copy differs")
        for item in before:
            if item["kind"] == "file" and os.path.samestat(
                (source / item["path"]).stat(), (output / item["path"]).stat()
            ):
                raise ValueError("Copy contains a source hard link")
        os.chmod(output, 0o700)

        with _root_lock(output, shared=False):
            store, reader = SnapshotStore(output), OfflineDataReader(output)
            coverage = {"original_success_jobs": 0, "recovered_with_usable_rows_jobs": 0,
                        "still_no_usable_data_jobs": 0, "recovery_attempted_jobs": 0,
                        "recovery_materialized_jobs": 0, "quarantine_only_jobs": 0,
                        "recovery_rejected_jobs": 0, "accepted_recovery_rows": 0, "quarantined_rows": 0}
            jobs, original_receipts, recovery_receipts, selection = [], [], [], []
            for job in parent["jobs"]:
                item = {"request": job["request"], "original_status": job["status"],
                        "outcome": "still_no_usable_data", "recovery_receipt_index": None}
                if job["status"] == "succeeded":
                    receipt = {"request": job["request"], **job["pin"]}
                    _verify_receipt(reader, receipt)
                    original_receipts.append(receipt)
                    coverage["original_success_jobs"] += 1
                    item["outcome"] = "original_success"
                else:
                    attempt = job["attempts"][-1] if job["attempts"] else {}
                    item["original_failure_category"] = attempt.get("error_category")
                    if attempt.get("error_category") == "data_quality":
                        record = _record_for_attempt(store, job, attempt)
                        pin = {"request": job["request"], "attempt_number": attempt["number"],
                               "snapshot_id": record["id"], "raw_sha256": record["raw_sha256"],
                               "observed_at": record["observed_at"]}
                        selection.append(pin)
                        item["selected_failed_attempt"] = pin
                        coverage["recovery_attempted_jobs"] += 1
                        try:
                            materialized = fundamental_recovery.replay_quarantined_fundamentals(store, record)
                        except ValueError:
                            coverage["recovery_rejected_jobs"] += 1
                            item["recovery_rejection"] = "recovery_contract_rejected_source"
                        else:
                            if (materialized["snapshot_id"] != record["id"]
                                    or materialized["raw_sha256"] != record["raw_sha256"]
                                    or materialized["normalizer"] != fundamental_recovery.NORMALIZER):
                                raise ValueError("Recovery materialization differs from its exact selected input")
                            receipt = {"request": job["request"], **materialized,
                                       "normalized_manifest_sha256": _manifest_sha(materialized)}
                            _verify_receipt(reader, receipt)
                            provenance = materialized["provenance"]
                            accepted = sum(table["rows"] for name, table in materialized["tables"].items()
                                           if name in {"annual", "quarterly"})
                            quarantined = materialized["tables"]["quarantine"]["rows"]
                            if (accepted != provenance["statement_rows"] or quarantined != provenance["quarantined_rows"]
                                    or bool(accepted) != provenance["usable_recovery"]):
                                raise ValueError("Recovery coverage differs from its stored tables")
                            item.update(recovery_status=provenance["recovery_status"],
                                        accepted_rows=accepted, quarantined_rows=quarantined,
                                        recovery_receipt_index=len(recovery_receipts))
                            recovery_receipts.append(receipt)
                            coverage["recovery_materialized_jobs"] += 1
                            coverage["accepted_recovery_rows"] += accepted
                            coverage["quarantined_rows"] += quarantined
                            if accepted:
                                coverage["recovered_with_usable_rows_jobs"] += 1
                                item["outcome"] = "recovered_with_usable_rows"
                            elif quarantined:
                                coverage["quarantine_only_jobs"] += 1
                    if item["outcome"] == "still_no_usable_data":
                        coverage["still_no_usable_data_jobs"] += 1
                jobs.append(item)

            denominator = len(parent["jobs"])
            if sum(coverage[key] for key in ("original_success_jobs", "recovered_with_usable_rows_jobs",
                                            "still_no_usable_data_jobs")) != denominator:
                raise ValueError("Recovery coverage lost a source batch job")
            if (output / "fundamental_batches" / run_id / "manifest.json").read_bytes() != (
                source / "fundamental_batches" / run_id / "manifest.json"
            ).read_bytes():
                raise ValueError("Original batch ledger changed in the copy")
            metadata = output / recovery_relative
            metadata.mkdir(parents=True, mode=0o700)
            shutil.copy2(universe_path, metadata / "universe.json")
            if (hashlib.sha256((metadata / "universe.json").read_bytes()).hexdigest() != universe_before[1]
                    or load_universe(metadata / "universe.json")["manifest_sha256"] != frozen["manifest_sha256"]):
                raise ValueError("Frozen universe changed while copying")
            inventory_file_sha = _write_json(metadata / "source-inventory.json", before)
            receipts = {"original_success_receipts": original_receipts, "recovery_receipts": recovery_receipts}
            receipts_sha = _write_json(metadata / "receipts.json", receipts)
            if inventory(source) != before or universe_before != (
                universe_path.stat().st_mtime_ns, hashlib.sha256(universe_path.read_bytes()).hexdigest()
            ):
                raise ValueError("Original source or frozen universe changed during recovery")
            manifest = {
                "schema": SCHEMA, "parent_run_id": run_id, "parent_manifest_sha256": parent["manifest_sha256"],
                "parent_config_sha256": parent["config_sha256"], "universe_sha256": frozen["manifest_sha256"],
                "universe_file_sha256": universe_before[1], "universe_scope": parent["config"]["universe_scope"],
                "source_inventory_sha256": _sha(before), "source_inventory_file_sha256": inventory_file_sha,
                "source_files_unchanged": True, "source_copy_mode": "independent_copy2_under_shared_batch_lock",
                "normalizer": fundamental_recovery.NORMALIZER,
                "code_commit": code_commit, "code_commit_basis": "explicit_caller_pin",
                "cli_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "normalizer_source_sha256": hashlib.sha256(Path(fundamental_recovery.__file__).read_bytes()).hexdigest(),
                "base_normalizer_source_sha256": hashlib.sha256(
                    Path(fundamental_snapshots.__file__).read_bytes()).hexdigest(),
                "normalization_policy_sha256": _sha(fundamental_recovery.POLICY),
                "python_version": platform.python_version(), "selection_sha256": _sha(selection),
                "receipts_file_sha256": receipts_sha, "planned_jobs": denominator, "coverage": coverage,
                "jobs": jobs, "eligibility": "not_certified", "network_requests": 0,
                "command": [sys.executable, "examples/recover_currency_statements.py", "--source-root", str(source),
                            "--output-root", str(output), "--run-id", run_id, "--universe", str(universe_path),
                            "--code-commit", code_commit],
            }
            manifest["manifest_sha256"] = _sha(manifest)
            _write_json(metadata / "manifest.json", manifest)
    return {key: manifest[key] for key in (
        "schema", "parent_manifest_sha256", "parent_config_sha256", "universe_sha256", "universe_scope",
        "source_inventory_sha256", "source_files_unchanged", "normalizer", "code_commit", "cli_source_sha256",
        "normalizer_source_sha256", "base_normalizer_source_sha256", "normalization_policy_sha256",
        "selection_sha256", "receipts_file_sha256", "manifest_sha256",
        "planned_jobs", "coverage", "eligibility", "network_requests",
    )}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args(argv)
    try:
        summary = recover(**vars(args))
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        parser.exit(1, "Recovery source, independent copy, universe or exact input pins rejected; no recovery certified.\n")
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
