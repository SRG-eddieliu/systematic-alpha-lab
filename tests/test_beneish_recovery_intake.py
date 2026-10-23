"""Synthetic stored tables exercise audit-only recovery intake, never real roots.

The fixture reuses the existing normalizer on explicitly filtered synthetic rows.
It describes the accepted schema without duplicating the engineering recovery
implementation or claiming raw/quarantine reconciliation by the research helper.
"""
import hashlib
import json
import socket
from copy import deepcopy
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
import requests

from systematic_alpha_lab.data_pipeline.fundamental_snapshots import normalize_reports
from systematic_alpha_lab.data_pipeline.offline_reader import DataRead, OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.factor_research.beneish_field_audit import (
    AUDIT_VERSION,
    CURRENCY_QUARANTINE_NORMALIZER,
    RECOVERY_AUDIT_VERSION,
    audit_beneish_field_coverage,
)
from systematic_alpha_lab.factor_research.beneish_pipeline import (
    FUNCTIONS,
    NORMALIZER,
    review_annual_beneish_snapshots,
)

PRIVATE_SYMBOL = "PRIVATEINTAKE77"
PRIVATE_AMOUNT = "76543210987654321098765432109876543210987"
QUARANTINE_SENTINEL = "PRIVATE-QUARANTINE-MUST-NOT-ENTER-AGGREGATE"


def make_store(tmp_path, *, functions=("INCOME_STATEMENT",), original=False, omit=None):
    store, selections = SnapshotStore(tmp_path / "synthetic-private-root"), []
    for function in functions:
        def report(date, currency, amount):
            return {"fiscalDateEnding": date, "reportedCurrency": currency,
                    "totalRevenue": amount, "totalAssets": amount, "operatingCashflow": amount}

        payload = {
            "symbol": PRIVATE_SYMBOL,
            "annualReports": [report("2024-12-31", "USD", PRIVATE_AMOUNT),
                              report("2023-12-31", "USD" if original else "None", QUARANTINE_SENTINEL),
                              report("2022-12-31", "EUR", "12.00")],
            "quarterlyReports": [report("2025-09-30", "USD", "4.00"),
                                 report("2025-06-30", "USD" if original else "None", QUARANTINE_SENTINEL),
                                 report("2025-03-31", "EUR", "5.00")],
        }
        request = {"symbol": PRIVATE_SYMBOL, "function": function}
        record = store.capture("alpha_vantage", request, json.dumps(payload).encode(),
                               observed_at="2026-10-23T05:00:00Z")
        filtered = {**payload, **{key: [row for row in payload[key] if row["reportedCurrency"] != "None"]
                                 for key in ("annualReports", "quarterlyReports")}}
        tables = normalize_reports(filtered, record, function, PRIVATE_SYMBOL)
        normalizer = NORMALIZER if original else CURRENCY_QUARANTINE_NORMALIZER
        if not original:
            for table, frame in tables.items():
                key = "annualReports" if table == "annual" else "quarterlyReports"
                positions = {pd.Timestamp(row["fiscalDateEnding"], tz="UTC"): index
                             for index, row in enumerate(payload[key])}
                tables[table] = frame.assign(normalizer=normalizer, source_report_key=key,
                                             source_row_index=frame.period_end.map(positions).astype("int64"))
            # Store diagnostic objects too: an audit must never substitute them
            # for missing financial tables or include their private row content.
            tables["quarantine"] = pd.DataFrame({
                "source_report_key": ["annualReports", "quarterlyReports"],
                "source_row_index": [1, 1], "source_row_json": [QUARANTINE_SENTINEL] * 2,
                "quarantine_reason": ["currency_missing"] * 2,
            })
            tables["normalization_audit"] = pd.DataFrame({"accepted_rows": [2, 2], "quarantined_rows": [1, 1]})
        if omit is not None:
            tables.pop(omit)
        store.publish_tables(record, normalizer, tables, provenance={
            "fixture_scope": "synthetic_schema_only_not_producer_acceptance",
            "input_snapshots": [{name: record[name] for name in ("id", "raw_sha256", "observed_at")}],
        })
        selections.append({"symbol": PRIVATE_SYMBOL, "function": function, "snapshot_id": record["id"]})
    return store, selections


def inventory(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class RecordingReader:
    def __init__(self, reader, transform=None):
        self.reader, self.transform, self.calls = reader, transform, []
        self.frames = []

    def catalog(self, **kwargs):
        raise AssertionError("Intake must not discover or choose a different version")

    def read(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["table"] in {"annual", "quarterly"}, "Diagnostic table requested as financial input"
        result = self.reader.read(**kwargs)
        frame, metadata = result.frame.copy(deep=True), deepcopy(result.metadata)
        if self.transform is not None:
            self.transform(frame, metadata, kwargs)
        self.frames.append((frame, frame.copy(deep=True)))
        return DataRead(frame=frame, metadata=metadata)


def run_audit(reader, selections):
    return audit_beneish_field_coverage(reader, selections=selections, normalizer=CURRENCY_QUARANTINE_NORMALIZER)


def test_actual_stored_recovery_tables_are_pinned_read_only_private_and_audit_only(tmp_path, monkeypatch):
    store, selections = make_store(tmp_path)
    before, selected_before = inventory(store.root), deepcopy(selections)

    def forbidden(*args, **kwargs):
        raise AssertionError("Network attempted")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    reader = RecordingReader(OfflineDataReader(store.root))
    result = run_audit(reader, selections)
    assert reader.calls == [{"snapshot_id": selections[0]["snapshot_id"],
                             "normalizer": CURRENCY_QUARANTINE_NORMALIZER, "table": table}
                            for table in ("annual", "quarterly")]
    # Sorting source dates keeps noncontiguous, descending source-array ordinals.
    assert all(frame.source_row_index.tolist() == [2, 0] for frame, _ in reader.frames)
    assert result["normalizer"] == CURRENCY_QUARANTINE_NORMALIZER
    assert result["audit_version"] == RECOVERY_AUDIT_VERSION
    assert result["intake_scope"] == "field_audit_only_not_annual_scoring_adapter_acceptance"
    assert result["raw_partition_status"] == "requires_separate_closed_handoff_reconciliation"
    assert result["row_basis"] == "currency_accepted_source_statement_rows_not_aligned_research_rows"
    assert result["diagnostic_tables_excluded"] == ["quarantine", "normalization_audit"]
    assert result["factor_calculated"] is result["standard_definition_satisfied"] is result["research_ready"] is False
    assert result["metadata_gate_status"].startswith("not_assessed")
    for item in result["groups"]:
        assert item["source_rows"] == item["fields"]["totalRevenue"]["finite_rows"] == 2
        assert item["provider_symbol_denominator"] == 1
    encoded = json.dumps(result, allow_nan=False)
    for private in [PRIVATE_SYMBOL, PRIVATE_AMOUNT, QUARANTINE_SENTINEL, str(store.root), "2026-10-23T05:00:00",
                    *[item["snapshot_id"] for item in selections], *[digest for digest, _ in before.values()]]:
        assert private not in encoded
    assert selections == selected_before and inventory(store.root) == before
    for frame, saved in reader.frames:
        pd.testing.assert_frame_equal(frame, saved)


@pytest.mark.parametrize("normalizer", [None, True, 1, [], {}, "av_fundamentals_v2", "latest",
                                       CURRENCY_QUARANTINE_NORMALIZER + "_other"])
def test_unsupported_normalizer_is_rejected_before_any_read(normalizer):
    class UnusedReader:
        def read(self, **kwargs):
            raise AssertionError("Normalizer validation must precede reading")

    with pytest.raises(ValueError, match="Unsupported explicitly pinned audit normalizer"):
        audit_beneish_field_coverage(UnusedReader(), selections=[], normalizer=normalizer)


@pytest.mark.parametrize("field,value", [
    ("normalizer", NORMALIZER), ("snapshot_id", "0" * 32), ("table", "quarterly"),
    ("provider", "other"), ("request", {"symbol": "OTHER", "function": "INCOME_STATEMENT"}),
    ("request", {"symbol": PRIVATE_SYMBOL, "function": "CASH_FLOW"}),
])
def test_recovery_returned_metadata_must_match_the_exact_requested_pin(tmp_path, field, value):
    store, selections = make_store(tmp_path)

    def transform(frame, metadata, kwargs):
        metadata[field] = value

    with pytest.raises(ValueError, match="source identity"):
        run_audit(RecordingReader(OfflineDataReader(store.root), transform), selections)


@pytest.mark.parametrize("field", ["snapshot_id", "normalizer", "provider", "symbol", "source_function", "period_type"])
@pytest.mark.parametrize("missing", [False, True])
def test_recovery_row_identity_cannot_be_hidden_behind_correct_metadata(tmp_path, field, missing):
    store, selections = make_store(tmp_path)

    def transform(frame, metadata, kwargs):
        if missing:
            frame.drop(columns=field, inplace=True)
        else:
            frame[field] = "OTHER"

    with pytest.raises(ValueError, match="row source identity"):
        run_audit(RecordingReader(OfflineDataReader(store.root), transform), selections)


@pytest.mark.parametrize("positions", [
    [True, False], [np.bool_(True), np.bool_(False)], [0.0, 2.0], [-1, 2], ["0", "2"],
    [None, 2], [pd.NA, 2], [Decimal("0"), Decimal("2")], [2, 2],
])
def test_recovery_positions_are_strict_unique_nonnegative_integers(tmp_path, positions):
    store, selections = make_store(tmp_path)

    def transform(frame, metadata, kwargs):
        frame["source_row_index"] = pd.Series(positions, index=frame.index, dtype=object)

    with pytest.raises(ValueError, match="unique nonnegative integers"):
        run_audit(RecordingReader(OfflineDataReader(store.root), transform), selections)


@pytest.mark.parametrize("field", ["source_report_key", "source_row_index", "currency", "reportedCurrency"])
def test_recovery_lineage_and_both_currency_columns_are_required(tmp_path, field):
    store, selections = make_store(tmp_path)

    def transform(frame, metadata, kwargs):
        frame.drop(columns=field, inplace=True)

    with pytest.raises(ValueError, match="lacks lineage"):
        run_audit(RecordingReader(OfflineDataReader(store.root), transform), selections)


@pytest.mark.parametrize("column", ["source_row_json", "reported_currency_json", "quarantine_reason", "source_rows",
                                    "accepted_rows", "quarantined_rows", "recovery_status", "usable_recovery", "eligibility"])
def test_diagnostic_columns_cannot_spoof_a_financial_table(tmp_path, column):
    store, selections = make_store(tmp_path)

    def transform(frame, metadata, kwargs):
        frame[column] = QUARANTINE_SENTINEL

    with pytest.raises(ValueError, match="diagnostic columns"):
        run_audit(RecordingReader(OfflineDataReader(store.root), transform), selections)


@pytest.mark.parametrize("report_key", ["quarterlyReports", "annual", None])
def test_recovery_row_array_must_match_the_requested_annual_table(tmp_path, report_key):
    store, selections = make_store(tmp_path)

    def transform(frame, metadata, kwargs):
        frame["source_report_key"] = report_key

    with pytest.raises(ValueError, match="source report array"):
        run_audit(RecordingReader(OfflineDataReader(store.root), transform), selections)


@pytest.mark.parametrize("currency,reported", [
    ("USD", "None"), ("USD", None), ("USD", "EUR"), ("usd", "usd"),
    (" USD", " USD"), ("US", "US"), (None, None), (True, True), ("123", "123"),
])
def test_missing_invalid_or_imputed_currency_is_rejected(tmp_path, currency, reported):
    store, selections = make_store(tmp_path)

    def transform(frame, metadata, kwargs):
        frame["currency"], frame["reportedCurrency"] = currency, reported

    with pytest.raises(ValueError, match="reported currency without imputation"):
        run_audit(RecordingReader(OfflineDataReader(store.root), transform), selections)


def test_three_letter_currency_format_is_not_promoted_to_a_registry_or_semantic_certificate(tmp_path):
    store, selections = make_store(tmp_path)

    def transform(frame, metadata, kwargs):
        frame["currency"] = frame["reportedCurrency"] = "ZZZ"

    result = run_audit(RecordingReader(OfflineDataReader(store.root), transform), selections)
    assert result["semantic_verification_status"] == "not_assessed"
    assert result["standard_definition_satisfied"] is result["research_ready"] is False


@pytest.mark.parametrize("missing", ["annual", "quarterly"])
def test_missing_financial_materialization_fails_instead_of_using_diagnostics(tmp_path, missing):
    store, selections = make_store(tmp_path, omit=missing)
    reader = RecordingReader(OfflineDataReader(store.root))
    with pytest.raises(KeyError, match="Pinned table"):
        run_audit(reader, selections)
    assert all(call["table"] in {"annual", "quarterly"} for call in reader.calls)
    assert reader.calls[-1]["table"] == missing


def test_empty_returned_financial_table_keeps_its_symbol_denominator(tmp_path):
    store, selections = make_store(tmp_path)

    def transform(frame, metadata, kwargs):
        frame.drop(frame.index, inplace=True)
        metadata["source_rows"] = metadata["returned_rows"] = 0

    result = run_audit(RecordingReader(OfflineDataReader(store.root), transform), selections)
    for item in result["groups"]:
        assert item["source_rows"] == 0 and item["source_tables"] == item["provider_symbol_denominator"] == 1
        assert item["fields"]["totalRevenue"]["provider_symbols_with_finite"] == 0


def test_default_v1_equals_explicit_v1_and_retains_the_original_output_contract(tmp_path):
    store, selections = make_store(tmp_path, original=True)
    reader = RecordingReader(OfflineDataReader(store.root))
    implicit = audit_beneish_field_coverage(reader, selections=selections)
    explicit = audit_beneish_field_coverage(reader, selections=selections, normalizer=NORMALIZER)
    assert implicit == explicit
    assert implicit["audit_version"] == AUDIT_VERSION == "beneish_field_coverage_v2"
    assert implicit["normalizer"] == NORMALIZER
    assert implicit["row_basis"] == "source_statement_rows_not_aligned_research_rows"
    assert not {"intake_scope", "raw_partition_status", "diagnostic_tables_excluded"}.intersection(implicit)
    assert all(call["normalizer"] == NORMALIZER for call in reader.calls)


def test_annual_scoring_adapter_never_falls_back_to_the_recovery_materialization(tmp_path):
    store, selections = make_store(tmp_path, functions=FUNCTIONS)
    pins = {item["function"]: item["snapshot_id"] for item in selections}
    reader = RecordingReader(OfflineDataReader(store.root))
    with pytest.raises(KeyError, match="Pinned normalized dataset"):
        review_annual_beneish_snapshots(reader, symbol=PRIVATE_SYMBOL, snapshot_ids=pins)
    assert reader.calls == [{"snapshot_id": pins["INCOME_STATEMENT"], "normalizer": NORMALIZER, "table": "annual"}]


def test_scoring_adapter_rejects_a_reader_returning_recovery_identity_for_v1(tmp_path):
    store, selections = make_store(tmp_path, functions=FUNCTIONS)
    pins = {item["function"]: item["snapshot_id"] for item in selections}

    class WrongVersionReader:
        def read(self, **kwargs):
            assert kwargs["normalizer"] == NORMALIZER
            return OfflineDataReader(store.root).read(**{**kwargs, "normalizer": CURRENCY_QUARANTINE_NORMALIZER})

    with pytest.raises(ValueError, match="source identity"):
        review_annual_beneish_snapshots(WrongVersionReader(), symbol=PRIVATE_SYMBOL, snapshot_ids=pins)
