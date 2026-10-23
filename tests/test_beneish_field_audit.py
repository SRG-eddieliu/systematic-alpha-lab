"""Field-gap counts use synthetic immutable source objects, never live requests."""
import hashlib
import json
import socket
from copy import deepcopy
from decimal import Decimal, localcontext

import numpy as np
import pandas as pd
import pytest
import requests

from systematic_alpha_lab.data_pipeline.fundamental_snapshots import replay_fundamentals
from systematic_alpha_lab.data_pipeline.offline_reader import DataRead, OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.factor_research.beneish_field_audit import audit_beneish_field_coverage
from systematic_alpha_lab.factor_research.beneish_pipeline import AV_CANDIDATES, NORMALIZER


def make_store(tmp_path, sources):
    store = SnapshotStore(tmp_path / "private-synthetic-root")
    selections = []
    for symbol, function, annual, quarterly in sources:
        def reports(values, table):
            return [{"fiscalDateEnding": f"{2000 + index}-{'12-31' if table == 'annual' else '03-31'}",
                     "reportedCurrency": "USD", **row} for index, row in enumerate(values)]

        payload = {"symbol": symbol, "annualReports": reports(annual, "annual"),
                   "quarterlyReports": reports(quarterly, "quarterly")}
        record = store.capture("alpha_vantage", {"symbol": symbol, "function": function},
                               json.dumps(payload, allow_nan=False).encode(), observed_at="2025-02-13T01:02:03+00:00")
        replay_fundamentals(store, record)
        selections.append({"symbol": symbol, "function": function, "snapshot_id": record["id"]})
    return store, selections


def group(result, function="INCOME_STATEMENT", table="annual"):
    return next(item for item in result["groups"] if item["function"] == function and item["table"] == table)


def fingerprints(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class TransformReader:
    def __init__(self, reader, transform):
        self.reader, self.transform, self.frames = reader, transform, []

    def read(self, **kwargs):
        result = self.reader.read(**kwargs)
        frame, metadata = result.frame.copy(deep=True), deepcopy(result.metadata)
        self.transform(frame, metadata, kwargs)
        self.frames.append((frame, frame.copy(deep=True)))
        return DataRead(frame=frame, metadata=metadata)


def one_source(tmp_path):
    return make_store(tmp_path, [("PRIVATEA77", "INCOME_STATEMENT", [{"totalRevenue": "7"}], [{"totalRevenue": "8"}])])


def test_synthetic_store_counts_are_offline_immutable_and_private(tmp_path, monkeypatch):
    values = [None, "", "None", "null", "  NULL  ", "not numeric", "NaN", "Inf", "-Infinity",
              "-2", "-0", "3", "1e-9999", "1e9999"]
    store, selections = make_store(tmp_path, [
        ("PRIVATEA77", "INCOME_STATEMENT", [{"totalRevenue": value} for value in values], [{"totalRevenue": "1"}]),
        ("PRIVATEB88", "INCOME_STATEMENT", [{"totalRevenue": None}], [{"totalRevenue": "None"}]),
        ("PRIVATEA77", "BALANCE_SHEET", [{"totalAssets": "98765432109876543210987654321"}], [{"totalAssets": "1"}]),
        ("PRIVATEC99", "CASH_FLOW", [{"operatingCashflow": "3"}], [{"operatingCashflow": "4"}]),
    ])
    before, selection_copy = fingerprints(store.root), deepcopy(selections)

    def forbidden(*args, **kwargs):
        raise AssertionError("Network attempted")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    result = audit_beneish_field_coverage(OfflineDataReader(store.root), selections=selections)
    counts = group(result)["fields"]["totalRevenue"]
    assert {key: counts[key] for key in ("source_rows", "missing_marker_rows", "invalid_numeric_rows",
                                       "nonfinite_numeric_rows", "finite_rows", "positive_rows", "zero_rows", "negative_rows")} == {
        "source_rows": 15, "missing_marker_rows": 6, "invalid_numeric_rows": 1,
        "nonfinite_numeric_rows": 3, "finite_rows": 5, "positive_rows": 3, "zero_rows": 1, "negative_rows": 1,
    }
    assert counts["provider_symbols_with_finite"] == 1 and counts["provider_symbol_denominator"] == 2
    assert group(result, "BALANCE_SHEET")["provider_symbol_denominator"] == 1
    assert group(result, "CASH_FLOW")["provider_symbol_denominator"] == 1
    absent = group(result)["fields"]["depreciation"]
    assert absent["column_absent_rows"] == 15 and absent["column_absent_tables"] == 2
    assert group(result, table="quarterly")["source_rows"] == 2
    assert group(result)["period_quality"]["duplicate_period_rows"] == 0  # Shared dates across symbols are not duplicates.
    for item in result["groups"]:
        for field in item["fields"].values():
            assert sum(field[key] for key in ("column_absent_rows", "missing_marker_rows", "invalid_numeric_rows",
                                             "nonfinite_numeric_rows", "boolean_rows", "finite_rows")) == field["source_rows"]
            assert field["positive_rows"] + field["zero_rows"] + field["negative_rows"] == field["finite_rows"]
            assert field["provider_symbols_with_finite"] <= field["provider_symbol_denominator"]
            assert field["semantic_status"] == "unverified_not_standard_accepted"
    encoded = json.dumps(result, allow_nan=False)
    for private in [str(store.root), "PRIVATEA77", "PRIVATEB88", "PRIVATEC99", "2025-02-13", "98765432109876543210987654321",
                    *[selection["snapshot_id"] for selection in selections], *[digest for digest, _ in before.values()]]:
        assert private not in encoded
    assert fingerprints(store.root) == before and selections == selection_copy
    assert result["factor_calculated"] is False and result["standard_definition_satisfied"] is False
    assert result["research_ready"] is False and result["network_operations"] == "none_requested"
    assert result["annual_duration_status"] == "not_inferred_from_source_annual_label"
    assert result == audit_beneish_field_coverage(OfflineDataReader(store.root), selections=list(reversed(selections)))


def test_native_scalar_invalid_boolean_and_null_categories_do_not_mutate_frames(tmp_path):
    values = [None, pd.NA, pd.NaT, True, np.bool_(False), float("nan"), float("inf"), Decimal("-Infinity"),
              {}, [], 1 + 2j, np.array([True, False]), np.array([1, 2]), Decimal("-0"), np.int64(-3), np.float64(2.5)]
    store, selections = make_store(tmp_path, [("SYNTH", "INCOME_STATEMENT", [{"totalRevenue": "1"} for _ in values], [{"totalRevenue": "1"}])])

    def transform(frame, metadata, kwargs):
        if kwargs["table"] == "annual":
            frame["totalRevenue"] = pd.Series(values, dtype=object)

    reader = TransformReader(OfflineDataReader(store.root), transform)
    result = audit_beneish_field_coverage(reader, selections=selections)
    counts = group(result)["fields"]["totalRevenue"]
    assert [counts[key] for key in ("missing_marker_rows", "boolean_rows", "nonfinite_numeric_rows", "invalid_numeric_rows", "finite_rows")] == [3, 2, 3, 5, 3]
    assert [counts[key] for key in ("positive_rows", "zero_rows", "negative_rows")] == [1, 1, 1]
    for frame, before in reader.frames:
        pd.testing.assert_frame_equal(frame, before)


def test_alternatives_never_fill_standard_candidates_and_all_twelve_are_present(tmp_path):
    store, selections = make_store(tmp_path, [
        ("SYNTH", "INCOME_STATEMENT", [{"depreciation": "None", "depreciationAndAmortization": "20", "netIncome": "9"}], [{"depreciationAndAmortization": "1"}]),
        ("SYNTH", "BALANCE_SHEET", [{"longTermDebt": "10", "currentLongTermDebt": "2"}], [{"totalAssets": "1"}]),
        ("SYNTH", "CASH_FLOW", [{"depreciationDepletionAndAmortization": "20"}], [{"operatingCashflow": "1"}]),
    ])
    result = audit_beneish_field_coverage(OfflineDataReader(store.root), selections=selections)
    canonical = {name for item in result["groups"] for field in item["fields"].values() for name in field["canonical_fields"]}
    assert canonical == set(AV_CANDIDATES)
    annual_is = group(result)["fields"]
    assert annual_is["depreciation"]["finite_rows"] == 0
    assert annual_is["depreciationAndAmortization"]["finite_rows"] == 1
    assert annual_is["depreciationAndAmortization"]["acceptance_constraint"] == "not_pure_depreciation_not_standard_accepted"
    assert annual_is["incomeBeforeExtraordinaryItems"]["column_absent_rows"] == 1
    assert annual_is["netIncome"]["finite_rows"] == 1
    assert group(result, "BALANCE_SHEET")["fields"]["longTermDebtNoncurrent"]["finite_rows"] == 0


def test_conditional_debt_difference_is_only_an_exact_sign_count(tmp_path):
    rows = [{"longTermDebt": total, "currentLongTermDebt": current} for total, current in [
        ("10", "2"), ("2", "2"), ("1", "2"), ("None", "2"), ("NaN", "2"),
        ("10000000000000000000000000000000000000001", "10000000000000000000000000000000000000002"),
        ("1e999999", "1e-999999"),
    ]]
    store, selections = make_store(tmp_path, [("SYNTH", "BALANCE_SHEET", rows, [{"longTermDebt": "1"}])])
    with localcontext() as context:
        context.prec = 1
        result = audit_beneish_field_coverage(OfflineDataReader(store.root), selections=selections)
    debt = group(result, "BALANCE_SHEET")["conditional_debt_diagnostic"]
    assert debt["jointly_finite_rows"] == 5
    assert debt["difference_nonnegative_rows"] == 3 and debt["difference_negative_rows"] == 2
    assert debt["status"] == "conditional_derivation_only_not_standard_accepted"
    assert debt["standard_field_filled"] is False
    assert group(result, "BALANCE_SHEET", "quarterly")["conditional_debt_diagnostic"]["jointly_finite_rows"] == 0
    assert len(result["groups"]) == 2  # Partial endpoint selection stays partial.


def test_metadata_coverage_counts_do_not_certify_annual_duration_or_expose_values(tmp_path):
    store, selections = make_store(tmp_path, [("SYNTH", "INCOME_STATEMENT", [{"totalRevenue": "1"} for _ in range(4)], [{"totalRevenue": "1"}])])

    def transform(frame, metadata, kwargs):
        if kwargs["table"] == "annual":
            frame["asset_id"] = [None, "private-issuer", "", "None"]
            frame["available_at"] = [pd.NaT, pd.Timestamp("2024-01-17", tz="UTC"), None, pd.NaT]
            frame["period_start"] = [None, "2001-01-01", "null", ""]
            frame["fiscal_year"] = [None, 2001, pd.NA, 2003]
            frame["amount_unit_status"] = ["unverified", "private-status", "None", "verified"]
            frame["flow_basis"] = ["stock", "annual", "ytd", "private-status"]

    result = audit_beneish_field_coverage(TransformReader(OfflineDataReader(store.root), transform), selections=selections)
    coverage = group(result)["metadata_coverage"]
    for field, count in (("asset_id", 1), ("available_at", 1), ("period_start", 1), ("fiscal_year", 2)):
        assert coverage[field] == {"column_present_tables": 1, "nonempty_rows": count}
    assert {key: coverage["amount_unit_status_counts"][key] for key in ("unverified", "other", "missing", "verified")} == dict.fromkeys(("unverified", "other", "missing", "verified"), 1)
    assert coverage["flow_basis_counts"]["other"] == 1
    assert group(result, table="quarterly")["metadata_coverage"]["period_start"]["column_present_tables"] == 0
    assert "private-" not in json.dumps(result)
    assert result["metadata_gate_status"].startswith("not_assessed")


def test_period_anomalies_are_counted_without_dates_or_repair(tmp_path):
    store, selections = make_store(tmp_path, [("SYNTH", "INCOME_STATEMENT", [{"totalRevenue": "1"} for _ in range(6)], [{"totalRevenue": "1"}])])

    def transform(frame, metadata, kwargs):
        if kwargs["table"] == "annual":
            frame["period_end"] = ["2000-12-31", "2000-12-31", None, "bad-date", "2004-12-31T12:00:00Z", 9]
        else:
            frame.drop(columns="period_end", inplace=True)

    result = audit_beneish_field_coverage(TransformReader(OfflineDataReader(store.root), transform), selections=selections)
    assert group(result)["period_quality"] == {"period_column_absent_tables": 0, "missing_period_rows": 1,
                                              "invalid_period_rows": 3, "duplicate_period_rows": 2,
                                              "duplicate_period_excess_rows": 1}
    assert group(result, table="quarterly")["period_quality"]["missing_period_rows"] == 1


@pytest.mark.parametrize("selections", [None, [], (), [{}], [{"symbol": "SYNTH", "function": "OTHER", "snapshot_id": "0" * 32}],
    [{"symbol": "synth", "function": "INCOME_STATEMENT", "snapshot_id": "0" * 32}],
    [{"symbol": "SYNTH", "function": "INCOME_STATEMENT", "snapshot_id": "not-an-id"}],
    [{"symbol": "SYNTH", "function": "INCOME_STATEMENT", "snapshot_id": "0" * 32, "extra": 1}],
    [{"symbol": "SYNTH", "function": "INCOME_STATEMENT", "snapshot_id": "0" * 32},
     {"symbol": "SYNTH", "function": "INCOME_STATEMENT", "snapshot_id": "1" * 32}]])
def test_invalid_or_duplicate_selections_are_rejected_before_any_read(selections):
    class UnusedReader:
        def read(self, **kwargs):
            raise AssertionError("Selection validation must finish before reading")

    with pytest.raises(ValueError):
        audit_beneish_field_coverage(UnusedReader(), selections=selections)


@pytest.mark.parametrize("field,value", [("snapshot_id", "0" * 32), ("normalizer", "other_v1"), ("table", "other"),
    ("provider", "other"), ("request", {"function": "CASH_FLOW", "symbol": "PRIVATEA77"}),
    ("request", {"function": "INCOME_STATEMENT", "symbol": "OTHER"}),
    ("request", {"function": "INCOME_STATEMENT", "symbol": "PRIVATEA77", "extra": "filter"})])
def test_returned_metadata_identity_must_match_every_pinned_component(tmp_path, field, value):
    store, selections = one_source(tmp_path)

    def transform(frame, metadata, kwargs):
        metadata[field] = value

    with pytest.raises(ValueError, match="source identity"):
        audit_beneish_field_coverage(TransformReader(OfflineDataReader(store.root), transform), selections=selections)


@pytest.mark.parametrize("field", ["snapshot_id", "normalizer", "provider", "symbol", "source_function", "period_type"])
@pytest.mark.parametrize("missing", [False, True])
def test_correct_metadata_cannot_hide_wrong_or_absent_row_identity(tmp_path, field, missing):
    store, selections = one_source(tmp_path)

    def transform(frame, metadata, kwargs):
        if missing:
            frame.drop(columns=field, inplace=True)
        else:
            frame[field] = "OTHER"

    with pytest.raises(ValueError, match="row source identity"):
        audit_beneish_field_coverage(TransformReader(OfflineDataReader(store.root), transform), selections=selections)


def test_missing_materialization_propagates_and_empty_tables_keep_the_symbol_denominator(tmp_path):
    store, selections = make_store(tmp_path, [("SYNTH", "INCOME_STATEMENT", [{"totalRevenue": "1"}], [])])
    with pytest.raises(KeyError, match="Pinned table"):
        audit_beneish_field_coverage(OfflineDataReader(store.root), selections=selections)
    store, selections = one_source(tmp_path / "both")

    def transform(frame, metadata, kwargs):
        frame.drop(frame.index, inplace=True)
        metadata["source_rows"] = metadata["returned_rows"] = 0

    result = audit_beneish_field_coverage(TransformReader(OfflineDataReader(store.root), transform), selections=selections)
    assert group(result)["source_rows"] == 0 and group(result)["source_tables"] == 1
    assert group(result)["fields"]["totalRevenue"]["provider_symbol_denominator"] == 1
    assert group(result)["fields"]["totalRevenue"]["provider_symbols_with_finite"] == 0


def test_projection_or_duplicate_columns_cannot_look_like_full_source_coverage(tmp_path):
    store, selections = one_source(tmp_path)

    def incomplete(frame, metadata, kwargs):
        metadata["source_rows"] += 1

    with pytest.raises(ValueError, match="complete pinned"):
        audit_beneish_field_coverage(TransformReader(OfflineDataReader(store.root), incomplete), selections=selections)

    class DuplicateColumnReader:
        def read(self, **kwargs):
            result = OfflineDataReader(store.root).read(**kwargs)
            frame = pd.concat([result.frame, result.frame[["totalRevenue"]]], axis=1)
            return DataRead(frame=frame, metadata=result.metadata)

    with pytest.raises(ValueError, match="unique source columns"):
        audit_beneish_field_coverage(DuplicateColumnReader(), selections=selections)


def test_only_fixed_normalizer_and_tables_are_requested(tmp_path):
    store, selections = one_source(tmp_path)
    calls = []

    class RecordingReader:
        def read(self, **kwargs):
            calls.append(kwargs)
            return OfflineDataReader(store.root).read(**kwargs)

    audit_beneish_field_coverage(RecordingReader(), selections=selections)
    assert calls == [{"snapshot_id": selections[0]["snapshot_id"], "normalizer": NORMALIZER, "table": table}
                     for table in ("annual", "quarterly")]
