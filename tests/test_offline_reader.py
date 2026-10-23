"""Pinned offline reads preserve source versions and reject corrupt evidence."""

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import requests

from systematic_alpha_lab.data_pipeline.batch_review import review_fundamental_batch
from systematic_alpha_lab.data_pipeline.fundamental_review import review_fundamental_snapshots
from systematic_alpha_lab.data_pipeline.fundamental_snapshots import replay_fundamentals
from systematic_alpha_lab.data_pipeline.monthly_price_snapshots import (
    SERIES,
    price_request,
    replay_monthly_prices,
)
from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.data_pipeline.quarterly_review import review_quarterly_snapshots
from systematic_alpha_lab.data_pipeline.sec_snapshots import replay_sec_facts, sec_request
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

NOW = "2020-08-01T20:00:00+00:00"
REQUEST = {"function": "INCOME_STATEMENT", "symbol": "SYNTH"}


def fundamental_payload(value="000100.00"):
    return {
        "symbol": "SYNTH",
        "annualReports": [{"fiscalDateEnding": "2019-12-31", "reportedCurrency": "USD", "netIncome": "400"}],
        "quarterlyReports": [
            {"fiscalDateEnding": "2020-03-31", "reportedCurrency": "USD", "netIncome": value},
            {"fiscalDateEnding": "2020-06-30", "reportedCurrency": "USD", "netIncome": "120"},
        ],
    }


def capture_fundamentals(store, value="000100.00", observed=NOW):
    record = store.capture("alpha_vantage", REQUEST, json.dumps(fundamental_payload(value)).encode(), observed_at=observed)
    return record, replay_fundamentals(store, record)


@pytest.fixture
def sample(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    record, manifest = capture_fundamentals(store)
    return store, record, manifest


def read_quarter(reader, record, manifest, **kwargs):
    return reader.read(snapshot_id=record["id"], normalizer=manifest["normalizer"], table="quarterly", **kwargs)


def update_record(store, record, **changes):
    with sqlite3.connect(store.catalog) as db:
        assignments = ",".join(f"{key}=?" for key in changes)
        db.execute(f"UPDATE snapshots SET {assignments} WHERE id=?", [*changes.values(), record["id"]])


def update_manifest(store, manifest, mutation):
    updated = deepcopy(manifest)
    mutation(updated)
    with sqlite3.connect(store.catalog) as db:
        db.execute("UPDATE datasets SET manifest_json=? WHERE snapshot_id=? AND normalizer=?",
                   (json.dumps(updated), manifest["snapshot_id"], manifest["normalizer"]))


def fingerprints(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def block_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An offline read attempted network access")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)


def test_read_and_discovery_are_network_free_and_leave_all_files_unchanged(sample, monkeypatch):
    store, record, manifest = sample
    before = fingerprints(store.root)
    block_network(monkeypatch)
    reader = OfflineDataReader(store.root)
    entries = reader.catalog(provider="alpha_vantage", request=REQUEST)
    assert {entry["table"] for entry in entries} == {"annual", "quarterly"}
    assert all(entry["snapshot_id"] == record["id"] for entry in entries)
    assert all(entry["request"] == REQUEST for entry in entries)
    result = read_quarter(reader, record, manifest)
    assert result.frame.netIncome.tolist() == ["000100.00", "120"]
    assert result.frame.available_at.isna().all()
    assert result.frame.asset_id.isna().all()
    assert result.metadata["source_rows"] == result.metadata["returned_rows"] == 2
    assert result.metadata["readiness"]["status"] == "not_certified"
    assert fingerprints(store.root) == before


def test_exact_snapshot_never_silently_uses_newer_observation(sample):
    store, record, manifest = sample
    newer, newer_manifest = capture_fundamentals(store, "999", "2020-08-02T20:00:00+00:00")
    reader = OfflineDataReader(store.root)
    assert read_quarter(reader, record, manifest).frame.netIncome.iloc[0] == "000100.00"
    assert read_quarter(reader, newer, newer_manifest).frame.netIncome.iloc[0] == "999"
    assert len(reader.catalog(provider="alpha_vantage", request=REQUEST)) == 4
    result = read_quarter(reader, record, manifest)
    result.frame.loc[0, "netIncome"] = "caller mutation"
    assert read_quarter(reader, record, manifest).frame.netIncome.iloc[0] == "000100.00"


def test_calendar_range_is_inclusive_empty_stays_empty_and_projection_keeps_metadata(sample):
    store, record, manifest = sample
    reader = OfflineDataReader(store.root)
    result = read_quarter(reader, record, manifest, start="2020-03-31", end="2020-03-31", fields=["netIncome"])
    assert result.frame.netIncome.tolist() == ["000100.00"]
    assert result.metadata["source_rows"] == 2 and result.metadata["returned_rows"] == 1
    assert result.metadata["date_column"] == "period_end"
    assert result.metadata["readiness"]["status"] == "not_certified"
    empty = read_quarter(reader, record, manifest, start="2021-01-01", end="2021-12-31")
    assert empty.frame.empty and empty.metadata["returned_rows"] == 0


@pytest.mark.parametrize("arguments", [
    {"start": "2020-04-01", "end": "2020-03-31"},
    {"start": "2020-02-30"},
    {"start": "2020-03-31T00:00:00Z"},
])
def test_invalid_ranges_are_rejected(sample, arguments):
    store, record, manifest = sample
    with pytest.raises(ValueError):
        read_quarter(OfflineDataReader(store.root), record, manifest, **arguments)


def test_missing_field_or_exact_identifier_cannot_fall_back(sample):
    store, record, manifest = sample
    reader = OfflineDataReader(store.root)
    with pytest.raises(KeyError):
        read_quarter(reader, record, manifest, fields=["not_a_source_field"])
    with pytest.raises(KeyError):
        reader.read(snapshot_id="0" * 32, normalizer=manifest["normalizer"], table="quarterly")
    with pytest.raises(KeyError):
        reader.read(snapshot_id=record["id"], normalizer="unknown_v1", table="quarterly")
    with pytest.raises(KeyError):
        reader.read(snapshot_id=record["id"], normalizer=manifest["normalizer"], table="unknown")
    assert reader.catalog(provider="alpha_vantage", request={**REQUEST, "symbol": "OTHER"}) == []


def test_missing_root_and_catalog_do_not_create_any_files(tmp_path):
    missing = tmp_path / "uncreated"
    with pytest.raises(FileNotFoundError):
        OfflineDataReader(missing).catalog(provider="alpha_vantage", request=REQUEST)
    assert not missing.exists()
    existing = tmp_path / "empty"
    existing.mkdir()
    with pytest.raises(FileNotFoundError):
        OfflineDataReader(existing).catalog(provider="alpha_vantage", request=REQUEST)
    assert list(existing.iterdir()) == []


def test_fresh_public_import_does_not_load_collection_or_credentials(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src"
    code = """
import importlib.abc
import socket
import sys

blocked = {
    'systematic_alpha_lab.data_pipeline.alpha_vantage_rest',
    'systematic_alpha_lab.data_pipeline.ingestion',
    'systematic_alpha_lab.data_pipeline.wrds_client',
}
class NoCollectionImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise AssertionError('Offline public import loaded a collection module: ' + fullname)
sys.meta_path.insert(0, NoCollectionImports())
def no_network(*args, **kwargs):
    raise AssertionError('Offline public import tried network access')
socket.create_connection = no_network
socket.socket.connect = no_network
from systematic_alpha_lab.data_pipeline import OfflineDataReader
assert OfflineDataReader.__name__ == 'OfflineDataReader'
assert blocked.isdisjoint(sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": str(source)}, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_catalog_symlink_cannot_cross_data_root(sample, tmp_path):
    store, _, _ = sample
    outside = tmp_path / "outside-catalog.sqlite3"
    outside.write_bytes(store.catalog.read_bytes())
    store.catalog.unlink()
    store.catalog.symlink_to(outside)
    with pytest.raises(ValueError):
        OfflineDataReader(store.root).catalog(provider="alpha_vantage", request=REQUEST)


def monthly_payload():
    rows = {date: {"1. open": "100", "2. high": "101", "3. low": "99", "4. close": "100",
                   "5. adjusted close": adjusted, "6. volume": "1000", "7. dividend amount": "0"}
            for date, adjusted in [("2020-05-29", "10"), ("2020-06-30", "11"), ("2020-07-31", "12")]}
    return {"Meta Data": {"1. Information": "Synthetic monthly prices", "2. Symbol": "IBM",
                          "3. Last Refreshed": "2020-07-31", "4. Time Zone": "US/Eastern"}, SERIES: rows}


def test_monthly_source_modes_do_not_mix_and_filter_uses_source_session_date(tmp_path):
    store = SnapshotStore(tmp_path)
    by_mode = {}
    for mode in ("user", "public_demo"):
        record = store.capture("alpha_vantage", price_request("IBM", mode), json.dumps(monthly_payload()).encode(),
                               observed_at=NOW)
        by_mode[mode] = record, replay_monthly_prices(store, record)
    reader = OfflineDataReader(tmp_path)
    for mode, (record, manifest) in by_mode.items():
        entries = reader.catalog(provider="alpha_vantage", request=price_request("IBM", mode))
        assert len(entries) == 1 and entries[0]["snapshot_id"] == record["id"]
        result = reader.read(snapshot_id=record["id"], normalizer=manifest["normalizer"], table="monthly_prices",
                             start="2020-06-30", end="2020-06-30")
        assert result.frame.access_mode.tolist() == [mode]
        assert result.frame.adjusted_close_text.tolist() == ["11"]
        assert result.metadata["date_column"] == "session_date"
        assert result.metadata["readiness"]["status"] == "not_certified"


@pytest.mark.parametrize("kind", ["raw", "table"])
def test_corrupt_object_is_rejected_before_data_is_returned(sample, kind):
    store, record, manifest = sample
    relative = record["raw_path"] if kind == "raw" else manifest["tables"]["quarterly"]["path"]
    path = store.root / relative
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(ValueError):
        read_quarter(OfflineDataReader(store.root), record, manifest)


@pytest.mark.parametrize("field,value", [
    ("snapshot_id", "0" * 32),
    ("normalizer", "substituted_v1"),
    ("raw_sha256", "0" * 64),
    ("observed_at", "2010-01-01T00:00:00+00:00"),
])
def test_manifest_identity_must_match_catalog(sample, field, value):
    store, record, manifest = sample
    update_manifest(store, manifest, lambda data: data.update({field: value}))
    with pytest.raises(ValueError):
        read_quarter(OfflineDataReader(store.root), record, manifest)


def test_catalog_request_identity_cannot_be_relabelled(sample):
    store, record, manifest = sample
    update_record(store, record, request_json=json.dumps({**REQUEST, "symbol": "OTHER"}))
    with pytest.raises(ValueError):
        read_quarter(OfflineDataReader(store.root), record, manifest)


@pytest.mark.parametrize("kind", ["raw", "table"])
@pytest.mark.parametrize("escape", ["relative", "absolute", "symlink"])
def test_catalog_paths_cannot_escape_data_root_even_if_bytes_and_hashes_match(sample, tmp_path, kind, escape):
    store, record, manifest = sample
    relative = record["raw_path"] if kind == "raw" else manifest["tables"]["quarterly"]["path"]
    outside = tmp_path / ("outside.parquet" if kind == "table" else "outside.json")
    outside.write_bytes((store.root / relative).read_bytes())
    if escape == "relative":
        replacement = "../" + outside.name
    elif escape == "absolute":
        replacement = str(outside)
    else:
        link = store.root / "escape-link"
        link.symlink_to(outside)
        replacement = link.name
    if kind == "raw":
        update_record(store, record, raw_path=replacement)
    else:
        update_manifest(store, manifest, lambda data: data["tables"]["quarterly"].update(path=replacement))
    with pytest.raises(ValueError):
        read_quarter(OfflineDataReader(store.root), record, manifest)


def capture_sec_pair(store):
    cik, accession = "0000000042", "0000000042-20-000001"
    submissions = {"cik": cik, "filings": {"recent": {
        "accessionNumber": [accession], "filingDate": ["2020-07-30"], "reportDate": ["2020-06-30"],
        "form": ["10-Q"], "acceptanceDateTime": ["2020-07-30T17:00:00-04:00"],
    }, "files": []}}
    facts = {"cik": 42, "facts": {"us-gaap": {"Assets": {"units": {"USD": [{
        "accn": accession, "filed": "2020-07-30", "form": "10-Q", "fy": 2020, "fp": "Q2",
        "end": "2020-06-30", "val": 1000,
    }]}}}}}
    submission = store.capture("sec", sec_request("submissions", cik), json.dumps(submissions).encode(), observed_at=NOW)
    record = store.capture("sec", sec_request("companyfacts", cik), json.dumps(facts).encode(), observed_at=NOW)
    manifest = replay_sec_facts(store, record, submission, concepts=[("us-gaap", "Assets")])
    return record, submission, manifest


def test_sec_reads_keep_unverified_availability_and_check_every_dependency(tmp_path):
    store = SnapshotStore(tmp_path)
    record, dependency, manifest = capture_sec_pair(store)
    reader = OfflineDataReader(tmp_path)
    result = reader.read(snapshot_id=record["id"], normalizer=manifest["normalizer"], table="facts")
    assert result.frame.value_text.tolist() == ["1000"]
    assert result.frame.available_at.isna().all()
    assert result.metadata["readiness"]["status"] == "not_certified"
    (store.root / dependency["raw_path"]).write_bytes(b'{"changed":"submission dependency"}')
    with pytest.raises(ValueError):
        reader.read(snapshot_id=record["id"], normalizer=manifest["normalizer"], table="facts")


def provider_review_records(store, symbol="SYNTH"):
    records = []
    for function, field, value in [("INCOME_STATEMENT", "netIncome", 10),
                                   ("CASH_FLOW", "operatingCashflow", 8),
                                   ("BALANCE_SHEET", "totalAssets", 100)]:
        annual, quarterly = [], []
        for year in (2020, 2021):
            assets = value + 20 * (year - 2020)
            row = {"fiscalDateEnding": f"{year}-12-31", "reportedCurrency": "USD",
                   field: str(assets if function == "BALANCE_SHEET" else value * 4)}
            if function == "CASH_FLOW":
                row["netIncome"] = "40"
            annual.append(row)
            for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
                quarter = {**row, "fiscalDateEnding": f"{year}-{month:02d}-{day}",
                           field: str(assets if function == "BALANCE_SHEET" else value)}
                if function == "CASH_FLOW":
                    quarter["netIncome"] = "10"
                quarterly.append(quarter)
        payload = {"symbol": symbol, "annualReports": annual, "quarterlyReports": quarterly}
        records.append(store.capture("alpha_vantage", {"function": function, "symbol": symbol},
                                     json.dumps(payload).encode(), observed_at="2022-02-01T00:00:00Z"))
    return records


@pytest.mark.parametrize("review,table", [
    (review_fundamental_snapshots, "reconciliation"),
    (review_quarterly_snapshots, "source_reconciliation"),
])
def test_provider_reconciliation_accepts_every_verified_endpoint_and_rejects_unrelated_function(tmp_path, review, table):
    store = SnapshotStore(tmp_path)
    manifest = review(store, provider_review_records(store))
    reader = OfflineDataReader(tmp_path)
    result = reader.read(snapshot_id=manifest["snapshot_id"], normalizer=manifest["normalizer"], table=table)
    assert set(result.frame.source_function) == {"INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW"}
    assert result.metadata["readiness"]["status"] == "not_certified"
    path = store.root / manifest["tables"][table]["path"]
    corrupted = result.frame.copy()
    corrupted.loc[0, "source_function"] = "EARNINGS"
    corrupted.to_parquet(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    update_manifest(store, manifest, lambda data: data["tables"][table].update(sha256=digest))
    with pytest.raises(ValueError):
        reader.read(snapshot_id=manifest["snapshot_id"], normalizer=manifest["normalizer"], table=table)


def test_materialized_staging_cannot_be_relabelled_as_another_capture(sample):
    store, record, manifest = sample
    newer, _ = capture_fundamentals(store, "999", "2020-08-02T20:00:00+00:00")
    path = store.root / manifest["tables"]["quarterly"]["path"]
    corrupted = pd.read_parquet(path)
    corrupted["snapshot_id"] = newer["id"]
    corrupted.to_parquet(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    update_manifest(store, manifest, lambda data: data["tables"]["quarterly"].update(sha256=digest))
    with pytest.raises(ValueError):
        read_quarter(OfflineDataReader(store.root), record, manifest)


def rewrite_derived_manifest(store, manifest, mutation):
    """Rebind the suffix too, so rejection exercises dependency semantics."""
    updated = deepcopy(manifest)
    mutation(updated)
    family = manifest["normalizer"].rsplit("_", 1)[0]
    suffix = hashlib.sha256(json.dumps(updated["provenance"], sort_keys=True).encode()).hexdigest()[:20]
    updated["normalizer"] = family + "_" + suffix
    with sqlite3.connect(store.catalog) as db:
        db.execute("UPDATE datasets SET normalizer=?,manifest_json=? WHERE snapshot_id=? AND normalizer=?",
                   (updated["normalizer"], json.dumps(updated), manifest["snapshot_id"], manifest["normalizer"]))
    return updated


def test_sec_facts_require_dependencies_even_after_suffix_is_recomputed(tmp_path):
    store = SnapshotStore(tmp_path)
    record, dependency, manifest = capture_sec_pair(store)
    changed = rewrite_derived_manifest(store, manifest, lambda data: data["provenance"].pop("input_snapshots"))
    (store.root / dependency["raw_path"]).write_bytes(b"missing provenance must not hide corrupt source")
    with pytest.raises(ValueError):
        OfflineDataReader(tmp_path).read(snapshot_id=record["id"], normalizer=changed["normalizer"], table="facts")


def test_sec_facts_reject_another_companys_valid_submissions_after_suffix_is_recomputed(tmp_path):
    store = SnapshotStore(tmp_path)
    record, dependency, manifest = capture_sec_pair(store)
    other = json.loads((store.root / dependency["raw_path"]).read_bytes())
    other["cik"] = "0000000099"
    substitute = store.capture("sec", sec_request("submissions", "0000000099"), json.dumps(other).encode(),
                               observed_at=NOW)
    item = {name: substitute[name] for name in ("id", "raw_sha256", "observed_at")}
    changed = rewrite_derived_manifest(store, manifest,
                                       lambda data: data["provenance"]["input_snapshots"].__setitem__(1, item))
    with pytest.raises(ValueError):
        OfflineDataReader(tmp_path).read(snapshot_id=record["id"], normalizer=changed["normalizer"], table="facts")


def test_sec_quarterly_requires_source_manifest_even_after_suffix_is_recomputed(tmp_path):
    store = SnapshotStore(tmp_path)
    record, _, source = capture_sec_pair(store)
    provenance = {"source_manifest": source}
    version = "sec_quarterly_review_v1_" + hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:20]
    frame = pd.DataFrame({"period_end": ["2020-06-30"], "calculation_ready": [False]})
    manifest = store.publish_tables(record, version, {"quarterly_review": frame}, provenance=provenance)
    changed = rewrite_derived_manifest(store, manifest, lambda data: data["provenance"].pop("source_manifest"))
    with pytest.raises(ValueError):
        OfflineDataReader(tmp_path).read(snapshot_id=record["id"], normalizer=changed["normalizer"], table="quarterly_review")


@pytest.mark.parametrize("kind", ["annual", "quarterly", "sec_quarterly", "batch"])
def test_known_reviews_reject_truncated_source_manifests_after_suffix_is_recomputed(tmp_path, kind):
    store = SnapshotStore(tmp_path)
    if kind == "sec_quarterly":
        record, _, source = capture_sec_pair(store)
        provenance = {"source_manifest": source}
        version = "sec_quarterly_review_v1_" + hashlib.sha256(
            json.dumps(provenance, sort_keys=True).encode()
        ).hexdigest()[:20]
        frame = pd.DataFrame({"period_end": ["2020-06-30"], "calculation_ready": [False]})
        manifest = store.publish_tables(record, version, {"quarterly_review": frame}, provenance=provenance)
    else:
        records = provider_review_records(store)
        if kind == "annual":
            manifest = review_fundamental_snapshots(store, records)
        elif kind == "quarterly":
            manifest = review_quarterly_snapshots(store, records)
        else:
            manifest = review_fundamental_batch(store, symbols=["SYNTH"])["manifest"]
    table = "annual_review" if kind == "annual" else "quarterly_review"
    reader = OfflineDataReader(tmp_path)
    original = reader.read(snapshot_id=manifest["snapshot_id"], normalizer=manifest["normalizer"], table=table)
    assert not original.frame.empty

    def truncate_sources(data):
        provenance = data["provenance"]
        if kind == "annual":
            sources = provenance["input_manifests"]
        elif kind == "quarterly":
            sources = [provenance["annual_review_manifest"]]
        elif kind == "sec_quarterly":
            sources = [provenance["source_manifest"]]
        else:
            sources = provenance["company_manifests"].values()
        for source in sources:
            # IDs alone cannot replace the complete registered dependency.
            for key in set(source) - {"snapshot_id", "normalizer"}:
                del source[key]

    changed = rewrite_derived_manifest(store, manifest, truncate_sources)
    with pytest.raises(ValueError):
        reader.read(snapshot_id=changed["snapshot_id"], normalizer=changed["normalizer"], table=table)


def test_catalog_rejects_incorrect_manifest_row_count(sample):
    store, _, manifest = sample
    update_manifest(store, manifest, lambda data: data["tables"]["quarterly"].update(rows=9999))
    with pytest.raises(ValueError):
        OfflineDataReader(store.root).catalog(provider="alpha_vantage", request=REQUEST)


def test_partial_batch_reads_all_tables_and_retains_explicit_missing_symbol(tmp_path):
    store = SnapshotStore(tmp_path)
    provider_review_records(store, symbol="SYN-A")
    batch = review_fundamental_batch(store, symbols=["SYN-A", "SYN-MISSING"])
    assert batch["status"] == "partial"
    manifest = batch["manifest"]
    reader = OfflineDataReader(tmp_path)
    assert set(manifest["tables"]) == {"annual_review", "quarterly_review", "reconciliation", "coverage"}
    for table in manifest["tables"]:
        result = reader.read(snapshot_id=manifest["snapshot_id"], normalizer=manifest["normalizer"], table=table)
        assert not result.frame.empty
        assert result.metadata["readiness"]["status"] == "not_certified"
        if table == "coverage":
            assert set(result.frame.provider_symbol) == {"SYN-A", "SYN-MISSING"}
            assert result.frame.loc[result.frame.provider_symbol.eq("SYN-MISSING"), "status"].tolist() == ["missing_captures"]
        else:
            assert set(result.frame.provider_symbol) == {"SYN-A"}
