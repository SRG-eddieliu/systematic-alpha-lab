"""Synthetic-only recovery tests; original source/version contracts stay fixed."""
import hashlib
import json
import socket
import sqlite3
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline import fundamental_recovery as recovery
from systematic_alpha_lab.data_pipeline import fundamental_snapshots
from systematic_alpha_lab.data_pipeline.fundamental_recovery import (
    NORMALIZER,
    normalize_quarantined_reports,
    replay_quarantined_fundamentals,
)
from systematic_alpha_lab.data_pipeline.fundamental_snapshots import normalize_reports, replay_fundamentals
from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

NOW = pd.Timestamp("2026-10-23T05:00:00Z")
REQUEST = {"function": "INCOME_STATEMENT", "symbol": "SYNTH"}


def report(date, currency="USD", amount="100.000"):
    return {"fiscalDateEnding": date, "reportedCurrency": currency, "netIncome": amount}


def payload():
    return {"symbol": "SYNTH",
            "annualReports": [report("2023-12-31", "EUR", "10.00"),
                              report("2022-12-31", "None", "456.125"),
                              report("2024-12-31", "USD", "20.000")],
            "quarterlyReports": [report("2025-09-30", "USD", "3.14"),
                                 report("2025-03-31", None, "89"),
                                 report("2025-06-30", "EUR", "99")]}


def capture(store, content=None, function="INCOME_STATEMENT", body=None):
    return store.capture("alpha_vantage", {**REQUEST, "function": function},
                         json.dumps(payload() if content is None else content).encode() if body is None else body,
                         observed_at=NOW)


def inventory(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_currency_quarantine_keeps_every_row_ordinal_amount_and_currency(tmp_path):
    store, content = SnapshotStore(tmp_path), payload()
    record = capture(store, content)
    before = deepcopy(content)
    with pytest.raises(ValueError, match="currency"):
        normalize_reports(content, record, REQUEST["function"], REQUEST["symbol"])
    tables = normalize_quarantined_reports(content, record, REQUEST["function"], REQUEST["symbol"])
    assert content == before
    assert tables["annual"].source_row_index.tolist() == [0, 2]
    assert tables["quarterly"].source_row_index.tolist() == [2, 0]
    assert tables["annual"].currency.tolist() == ["EUR", "USD"]
    assert tables["quarterly"].currency.tolist() == ["EUR", "USD"]
    assert tables["annual"].netIncome.tolist() == ["10.00", "20.000"]
    assert tables["quarterly"].netIncome.tolist() == ["99", "3.14"]
    quarantined = tables["quarantine"]
    assert quarantined.source_row_index.tolist() == [1, 1]
    assert quarantined.currency.isna().all()
    assert quarantined.quarantine_reason.tolist() == ["currency_missing", "currency_missing"]
    for row in quarantined.itertuples():
        source = content[row.source_report_key][row.source_row_index]
        assert json.loads(row.source_row_json) == source
        assert json.loads(row.reported_currency_json) == source["reportedCurrency"]
        assert source["netIncome"] in {"456.125", "89"}
    for row in tables["normalization_audit"].itertuples():
        accepted = tables[row.period_type]
        rejected = quarantined.loc[quarantined.source_report_key.eq(row.source_report_key)]
        assert row.source_rows == len(content[row.source_report_key]) == row.accepted_rows + row.quarantined_rows
        assert row.accepted_rows == len(accepted) == 2
        assert row.quarantined_rows == len(rejected) == 1
        assert sorted(accepted.source_row_index.tolist() + rejected.source_row_index.tolist()) == [0, 1, 2]
    assert all(frame.normalizer.eq(NORMALIZER).all() for frame in tables.values())


@pytest.mark.parametrize("currency", [None, "", "None", "null", "usd", " USD", "US", "GBp", 123, ["USD"], {"ccy": "USD"}, True])
def test_bad_currency_values_are_not_coerced_or_filled(tmp_path, currency):
    content = payload()
    content["annualReports"][1]["reportedCurrency"] = currency
    store = SnapshotStore(tmp_path)
    record = capture(store, content)
    tables = normalize_quarantined_reports(content, record, REQUEST["function"], REQUEST["symbol"])
    row = tables["quarantine"].loc[tables["quarantine"].source_report_key.eq("annualReports")].iloc[0]
    assert pd.isna(row.currency)
    assert json.loads(row.reported_currency_json) == currency
    assert json.loads(row.source_row_json) == content["annualReports"][1]


def test_absent_currency_field_stays_distinct_from_json_null(tmp_path):
    content = payload()
    del content["annualReports"][1]["reportedCurrency"]
    store = SnapshotStore(tmp_path)
    tables = normalize_quarantined_reports(content, capture(store, content), REQUEST["function"], REQUEST["symbol"])
    annual, quarter = tables["quarantine"].iloc[0], tables["quarantine"].iloc[1]
    assert annual.quarantine_reason == "currency_field_missing" and pd.isna(annual.reported_currency_json)
    assert quarter.quarantine_reason == "currency_missing" and quarter.reported_currency_json == "null"


def test_large_json_integer_and_null_cannot_publish_after_pandas_float_coercion(tmp_path):
    content = {"symbol": "SYNTH", "annualReports": [report("2023-12-31", amount=9007199254740993),
                                                   report("2024-12-31", amount=None)], "quarterlyReports": []}
    store = SnapshotStore(tmp_path)
    record = capture(store, content)
    # Reproduce the inherited inference risk without changing the v1 normalizer.
    inherited = normalize_reports(content, record, REQUEST["function"], REQUEST["symbol"])["annual"]
    assert inherited.netIncome.dtype == "float64"
    assert int(inherited.netIncome.iloc[0]) != content["annualReports"][0]["netIncome"]
    raw_before = (tmp_path / record["raw_path"]).read_bytes()
    with pytest.raises(ValueError, match="source field type/value was not preserved"):
        replay_quarantined_fundamentals(store, record)
    assert store.dataset(record["id"], NORMALIZER) is None
    assert (tmp_path / record["raw_path"]).read_bytes() == raw_before


def test_large_integer_string_and_source_none_token_are_preserved_verbatim(tmp_path):
    content = {"symbol": "SYNTH", "annualReports": [report("2023-12-31", amount="9007199254740993"),
                                                   report("2024-12-31", amount="None")], "quarterlyReports": []}
    store = SnapshotStore(tmp_path)
    manifest = replay_quarantined_fundamentals(store, capture(store, content))
    result = OfflineDataReader(tmp_path).read(snapshot_id=manifest["snapshot_id"], normalizer=NORMALIZER, table="annual")
    assert result.frame.netIncome.tolist() == ["9007199254740993", "None"]
    assert manifest["provenance"]["statement_rows"] == 2


@pytest.mark.parametrize("amounts", [[1, 2], [2**63, 2**63 + 1], [1.25, 2.5], [-0.0, 0.0], [True, False], [None, None]])
def test_exact_numeric_scalar_types_survive_without_false_rejection(tmp_path, amounts):
    content = {"symbol": "SYNTH", "annualReports": [report("2023-12-31", amount=amounts[0]),
                                                   report("2024-12-31", amount=amounts[1])], "quarterlyReports": []}
    store = SnapshotStore(tmp_path)
    manifest = replay_quarantined_fundamentals(store, capture(store, content))
    frame = OfflineDataReader(tmp_path).read(snapshot_id=manifest["snapshot_id"], normalizer=NORMALIZER, table="annual").frame
    for index, amount in enumerate(amounts):
        assert recovery._preserves_source_value(amount, frame.at[index, "netIncome"])


@pytest.mark.parametrize("amounts", [[1, None], [1, 1.0]])
def test_even_exact_small_integer_to_float_coercion_is_explicitly_rejected(tmp_path, amounts):
    content = {"symbol": "SYNTH", "annualReports": [report("2023-12-31", amount=amounts[0]),
                                                   report("2024-12-31", amount=amounts[1])], "quarterlyReports": []}
    store = SnapshotStore(tmp_path)
    record = capture(store, content)
    with pytest.raises(ValueError, match="source field type/value was not preserved"):
        replay_quarantined_fundamentals(store, record)
    assert store.dataset(record["id"], NORMALIZER) is None


@pytest.mark.parametrize("source,actual,preserved", [
    (9007199254740993, np.int64(9007199254740993), True),
    (2**63 + 1, np.uint64(2**63 + 1), True), (1.25, np.float64(1.25), True), (True, np.bool_(True), True),
    (1, 1.0, False), (1, True, False), (True, 1, False), ("1", 1, False), (-0.0, 0.0, False),
    (None, pd.NA, True), (None, float("nan"), True), (None, "None", False),
])
def test_exact_preservation_policy_does_not_use_loose_python_numeric_equality(source, actual, preserved):
    assert recovery._preserves_source_value(source, actual) is preserved


@pytest.mark.parametrize("issue", [
    "duplicate_bad_with_good", "duplicate_bad_with_bad", "missing_date", "invalid_date", "future",
    "reserved", "new_metadata", "missing_array", "non_array", "non_object", "symbol", "notice",
])
def test_complete_source_errors_cannot_disappear_through_currency_filtering(tmp_path, issue):
    content = payload()
    bad = content["annualReports"][1]
    if issue == "duplicate_bad_with_good": bad["fiscalDateEnding"] = content["annualReports"][0]["fiscalDateEnding"]
    if issue == "duplicate_bad_with_bad": content["annualReports"].append(deepcopy(bad))
    if issue == "missing_date": del bad["fiscalDateEnding"]
    if issue == "invalid_date": bad["fiscalDateEnding"] = "not-a-date"
    if issue == "future": bad["fiscalDateEnding"] = "2027-01-01"
    if issue == "reserved": bad["available_at"] = "2020-01-01"
    if issue == "new_metadata": bad["source_row_index"] = 999
    if issue == "missing_array": del content["quarterlyReports"]
    if issue == "non_array": content["quarterlyReports"] = {}
    if issue == "non_object": content["quarterlyReports"].append("not a report")
    if issue == "symbol": content["symbol"] = "OTHER"
    if issue == "notice": content["Note"] = "provider notice"
    store = SnapshotStore(tmp_path)
    # Successful snapshot catalog admission itself rejects provider notices.
    if issue == "notice":
        record = capture(store)
        with pytest.raises(ValueError):
            normalize_quarantined_reports(content, record, REQUEST["function"], REQUEST["symbol"])
    else:
        record = capture(store, content)
        with pytest.raises(ValueError):
            replay_quarantined_fundamentals(store, record)
        assert store.dataset(record["id"], NORMALIZER) is None


@pytest.mark.parametrize("annual,quarterly,status,accepted,quarantined", [
    ([], [], "no_reports", 0, 0),
    ([report("2024-12-31", "None")], [], "quarantine_only", 0, 1),
    ([], [report("2025-03-31", None)], "quarantine_only", 0, 1),
    ([report("2024-12-31")], [], "accepted", 1, 0),
])
def test_empty_arrays_and_quarantine_only_never_claim_usable_statement_recovery(
    tmp_path, annual, quarterly, status, accepted, quarantined,
):
    store = SnapshotStore(tmp_path)
    record = capture(store, {"symbol": "SYNTH", "annualReports": annual, "quarterlyReports": quarterly})
    manifest = replay_quarantined_fundamentals(store, record)
    provenance = manifest["provenance"]
    assert provenance["recovery_status"] == status
    assert provenance["usable_recovery"] is bool(accepted)
    assert provenance["eligibility"] == "not_certified"
    assert provenance["statement_rows"] == accepted and provenance["quarantined_rows"] == quarantined
    assert provenance["source_counts"]["annualReports"]["source_rows"] == len(annual)
    assert provenance["source_counts"]["quarterlyReports"]["source_rows"] == len(quarterly)
    reader = OfflineDataReader(tmp_path)
    audit = reader.read(snapshot_id=record["id"], normalizer=NORMALIZER, table="normalization_audit").frame
    assert len(audit) == 2 and audit.source_rows.sum() == accepted + quarantined
    assert manifest["tables"]["quarantine"]["rows"] == quarantined
    if not accepted:
        assert not {"annual", "quarterly"}.intersection(manifest["tables"])


@pytest.mark.parametrize("function,flow", [("INCOME_STATEMENT", "unverified"), ("CASH_FLOW", "unverified"), ("BALANCE_SHEET", "stock")])
def test_unverified_units_identity_availability_and_flow_contract_are_preserved(tmp_path, function, flow):
    store = SnapshotStore(tmp_path)
    manifest = replay_quarantined_fundamentals(store, capture(store, function=function))
    reader = OfflineDataReader(tmp_path)
    for name in ("annual", "quarterly", "quarantine"):
        frame = reader.read(snapshot_id=manifest["snapshot_id"], normalizer=NORMALIZER, table=name).frame
        assert frame.flow_basis.eq(flow).all() and frame.amount_unit_status.eq("unverified").all()
        assert frame.available_at.isna().all() and frame.asset_id.isna().all()
        assert frame.availability_basis.eq("not_supplied").all()
        assert frame.identifier_basis.eq("provider_symbol_unmapped").all()


def test_replay_is_idempotent_and_all_tables_read_offline_without_writes(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    record = capture(store)
    first = replay_quarantined_fundamentals(store, record)
    before = inventory(tmp_path)
    assert replay_quarantined_fundamentals(store, record) == first
    assert inventory(tmp_path) == before

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline recovery attempted network access")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    reader = OfflineDataReader(tmp_path)
    entries = reader.catalog(provider="alpha_vantage", request=REQUEST)
    assert {row["table"] for row in entries} == set(first["tables"])
    for name in first["tables"]:
        result = reader.read(snapshot_id=record["id"], normalizer=NORMALIZER, table=name)
        assert len(result.frame) == first["tables"][name]["rows"]
    assert inventory(tmp_path) == before


def test_new_materialization_does_not_replace_v1_raw_tables_or_original_run(tmp_path):
    store = SnapshotStore(tmp_path)
    content = {"symbol": "SYNTH", "annualReports": [report("2024-12-31")], "quarterlyReports": []}
    record = capture(store, content)
    original = replay_fundamentals(store, record)
    old_source = Path(fundamental_snapshots.__file__).read_bytes()
    ledger = tmp_path / "fundamental_batches/original/manifest.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"closed_original_run":"unchanged"}')
    paths = [tmp_path / record["raw_path"], ledger, *(tmp_path / item["path"] for item in original["tables"].values())]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    new = replay_quarantined_fundamentals(store, record)
    assert new["normalizer"] != original["normalizer"]
    assert store.dataset(record["id"], fundamental_snapshots.NORMALIZER) == original
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before
    assert Path(fundamental_snapshots.__file__).read_bytes() == old_source


@pytest.mark.parametrize("drift", ["own_source", "base_source", "policy", "counts"])
def test_same_normalizer_version_rejects_code_policy_and_accounting_drift(tmp_path, monkeypatch, drift):
    store = SnapshotStore(tmp_path / "data")
    record = capture(store)
    first = replay_quarantined_fundamentals(store, record)
    if drift in {"own_source", "base_source"}:
        other = tmp_path / "changed_source.py"
        other.write_text("# Deliberately different source for version pin testing\n")
        monkeypatch.setattr(recovery if drift == "own_source" else fundamental_snapshots, "__file__", str(other))
    if drift == "policy":
        monkeypatch.setattr(recovery, "POLICY", {**recovery.POLICY, "invalid_currency": "changed policy"})
    if drift == "counts":
        changed = deepcopy(first)
        changed["provenance"]["source_counts"]["annualReports"]["accepted_rows"] += 1
        with sqlite3.connect(store.catalog) as db:
            db.execute("UPDATE datasets SET manifest_json=? WHERE snapshot_id=? AND normalizer=?",
                       (json.dumps(changed), record["id"], NORMALIZER))
    with pytest.raises(ValueError, match="source/policy/provenance changed"):
        replay_quarantined_fundamentals(store, record)


@pytest.mark.parametrize("corrupt", ["raw", "quarantine"])
def test_corrupt_raw_or_materialized_quarantine_is_rejected(tmp_path, corrupt):
    store = SnapshotStore(tmp_path)
    record = capture(store)
    manifest = replay_quarantined_fundamentals(store, record)
    relative = record["raw_path"] if corrupt == "raw" else manifest["tables"]["quarantine"]["path"]
    (tmp_path / relative).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        replay_quarantined_fundamentals(store, record)


@pytest.mark.parametrize("field,value", [("raw_sha256", "0" * 64), ("observed_at", "2020-01-01T00:00:00Z"),
                                         ("request_json", '{"function":"CASH_FLOW","symbol":"SYNTH"}')])
def test_caller_cannot_relabel_registered_source_pins(tmp_path, field, value):
    store = SnapshotStore(tmp_path)
    record = capture(store)
    changed = {**record, field: value}
    with pytest.raises(ValueError, match="catalog pin"):
        replay_quarantined_fundamentals(store, changed)
    assert store.dataset(record["id"], NORMALIZER) is None


@pytest.mark.parametrize("invalid", ["duplicate_json_field", "nonfinite_json"])
def test_replay_rejects_ambiguous_or_nonfinite_source_json(tmp_path, invalid):
    body = json.dumps(payload()).encode()
    if invalid == "duplicate_json_field":
        body = body.replace(b'"reportedCurrency": "None"', b'"reportedCurrency": "USD", "reportedCurrency": "None"')
    else:
        body = body.replace(b'"netIncome": "456.125"', b'"netIncome": NaN')
    store = SnapshotStore(tmp_path)
    record = capture(store, body=body)
    with pytest.raises(ValueError, match="Duplicate source JSON|Nonfinite source JSON"):
        replay_quarantined_fundamentals(store, record)
    assert store.dataset(record["id"], NORMALIZER) is None
