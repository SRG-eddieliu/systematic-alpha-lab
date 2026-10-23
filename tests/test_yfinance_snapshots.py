"""Synthetic library-return snapshots: precision, identity and pinned replay."""
from copy import deepcopy
import hashlib
import json
import socket
import sqlite3

import numpy as np
import pandas as pd
import pytest
import requests

from systematic_alpha_lab.data_pipeline import yfinance_snapshots as yf
from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

START = "2001-04-02T10:00:00+00:00"
FINISH = "2001-04-02T10:00:01+00:00"


def sample_frame():
    return pd.DataFrame([
        [9007199254740993, None, np.uint64(18446744073709551615)],
        [0.12345678901234566, -0.0, np.float64("inf")],
        ["00123", True, pd.NA],
        [np.float64("nan"), pd.NaT, np.float32(1.25)],
    ], index=pd.Index(["NetIncome", "NetIncome", "Special", "Missing"], name="source metric"),
        columns=pd.DatetimeIndex(["2000-12-31", "1999-12-31", "2000-12-31"], name="source period"), dtype=object)


def capture(store, frame=None, **changes):
    options = {"symbol": "SYNTH", "method": "get_income_stmt", "yfinance_version": "0.2.synthetic",
               "started_at": START, "finished_at": FINISH}
    options.update(changes)
    return yf.capture_yfinance_statement(store, sample_frame() if frame is None else frame, **options)


def inventory(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def denied(*args, **kwargs):
    raise AssertionError("Library snapshots must not fetch, load credentials or select latest")


def offline(monkeypatch):
    from systematic_alpha_lab.data_pipeline import config_loader

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(requests.Session, "request", denied)
    monkeypatch.setattr(SnapshotStore, "latest", denied)
    monkeypatch.setattr(config_loader, "load_credentials", denied)


@pytest.mark.parametrize("value", [
    None, pd.NA, pd.NaT, True, False, np.bool_(True), 9007199254740993, -(2**100),
    np.int8(-128), np.int64(-(2**63)), np.uint64(2**64 - 1),
    0.12345678901234566, -0.0, float("nan"), float("inf"), -float("inf"),
    np.float16(1.125), np.float32(0.123), np.float64(-0.0), np.float32("nan"),
    "00123.4500", "None", "", "éarnings",
    pd.Timestamp("2000-12-31T12:01:02.123456789"),
    pd.Timestamp("2000-12-31T12:01:02.123456789", tz="America/Toronto"),
])
def test_scalar_codec_roundtrips_types_values_missing_states_and_signed_zero(value):
    encoded = yf.encode_scalar(value)
    assert set(encoded) == {"kind", "value"} and all(isinstance(item, str) for item in encoded.values())
    encoded = json.loads(json.dumps(encoded, allow_nan=False))
    assert yf.encode_scalar(yf.decode_scalar(encoded)) == encoded
    if value is None or value is pd.NA or value is pd.NaT:
        assert yf.decode_scalar(encoded) is value


@pytest.mark.parametrize("encoded", [
    {"kind": "int", "value": "01"}, {"kind": "np_int8", "value": "128"},
    {"kind": "float", "value": "0.123456789"}, {"kind": "np_float32", "value": "0x1.0000000000001p+0"},
    {"kind": "none", "value": "null"}, {"kind": "bool", "value": "1"},
    {"kind": "string", "value": "x", "extra": "y"}, {"kind": "unknown", "value": "x"},
])
def test_scalar_codec_rejects_noncanonical_or_lossy_encodings(encoded):
    with pytest.raises(ValueError):
        yf.decode_scalar(encoded)


@pytest.mark.parametrize("value", [complex(1, 2), [1], {"amount": 1}, np.datetime64("2000-12-31")])
def test_scalar_codec_rejects_unsupported_types_without_implicit_stringification(value):
    with pytest.raises(TypeError):
        yf.encode_scalar(value)


def test_encoded_frame_keeps_duplicate_axes_order_dtypes_and_exact_object_scalars():
    frame = sample_frame()
    before = frame.copy(deep=True)
    encoded = yf.encode_dataframe(frame)
    assert encoded["shape"] == [4, 3] and encoded["dtypes"] == ["object"] * 3
    assert encoded["index"]["labels"][0] == encoded["index"]["labels"][1]
    assert encoded["columns"]["labels"][0] == encoded["columns"]["labels"][2]
    assert encoded["data"][0][0] == {"kind": "int", "value": "9007199254740993"}
    assert encoded["data"][0][2] == {"kind": "np_uint64", "value": "18446744073709551615"}
    assert encoded["data"][1][1] == {"kind": "float", "value": "-0x0.0p+0"}
    assert [encoded["data"][row][column]["kind"] for row, column in ((0, 1), (2, 2), (3, 0), (3, 1))] == [
        "none", "pandas_na", "np_float64", "nat"
    ]
    assert json.loads(json.dumps(encoded, allow_nan=False)) == encoded
    pd.testing.assert_frame_equal(frame, before, check_exact=True)


@pytest.mark.parametrize("axis", ["index", "columns"])
def test_frame_codec_rejects_multilevel_axes_instead_of_flattening_them(axis):
    frame = pd.DataFrame([[1]])
    setattr(frame, axis, pd.MultiIndex.from_tuples([("statement", "label")]))
    with pytest.raises(ValueError, match="MultiIndex"):
        yf.encode_dataframe(frame)


def test_capture_and_offline_replay_preserve_every_cell_without_certifying_metadata(tmp_path, monkeypatch):
    offline(monkeypatch)
    store, frame = SnapshotStore(tmp_path), sample_frame()
    result = capture(store, frame)
    record, manifest = result["record"], result["manifest"]
    request = json.loads(record["request_json"])
    assert request["frequency"] == "yearly" and request["pretty"] is False
    content = store.read_payload(record)
    assert content["response_layer"] == "library_dataframe" and content["http_inputs"] == []
    assert content["dataframe"] == yf.encode_dataframe(frame)
    before = inventory(tmp_path)
    reader = OfflineDataReader(tmp_path)
    catalog = reader.catalog(provider=yf.PROVIDER, request=request)
    assert {item["table"] for item in catalog} == {"facts", "audit"}
    facts = reader.read(snapshot_id=record["id"], normalizer=yf.NORMALIZER, table="facts").frame
    assert len(facts) == frame.size and not list(facts.select_dtypes(include="floating").columns)
    assert facts.source_row_position.tolist() == [row for row in range(4) for _ in range(3)]
    assert facts.source_column_position.tolist() == list(range(3)) * 4
    for row in facts.itertuples():
        expected = yf.encode_scalar(frame.iat[row.source_row_position, row.source_column_position])
        assert (row.value_kind, row.value) == (expected["kind"], expected["value"])
    assert facts.original_period_timezone.isna().all() and facts.period_end.dt.tz is not None
    assert facts.available_at.isna().all() and facts.asset_id.isna().all() and facts.currency.isna().all()
    assert facts.statement_scope.eq("unknown").all() and facts.amount_unit_status.eq("unknown").all()
    assert not facts.source_symbol_verified.any()
    assert manifest["provenance"]["http_raw_capture_status"] == "not_captured"
    assert manifest["provenance"]["issuer_identity_status"] == "unknown"
    assert manifest["provenance"]["eligibility"] == "candidate_only_not_certified"
    audit = reader.read(snapshot_id=record["id"], normalizer=yf.NORMALIZER, table="audit").frame.iloc[0]
    assert (audit.source_cells, audit.finite_numeric_cells, audit.missing_cells) == (12, 5, 4)
    assert (audit.nonfinite_cells, audit.nonnumeric_cells) == (1, 2)
    assert yf.replay_yfinance_statement(store, record) == manifest
    assert inventory(tmp_path) == before
    # Source calendar filtering does not imply historical availability.
    selected = reader.read(snapshot_id=record["id"], normalizer=yf.NORMALIZER, table="facts",
                           start="1999-12-31", end="1999-12-31")
    assert len(selected.frame) == 4 and selected.metadata["readiness"]["status"] == "not_certified"


@pytest.mark.parametrize("frame", [pd.DataFrame(), pd.DataFrame(index=["metric"]),
                                 pd.DataFrame(columns=pd.DatetimeIndex(["2000-12-31"]))])
def test_empty_frames_still_have_immutable_capture_and_unavailable_audit(tmp_path, frame):
    store = SnapshotStore(tmp_path)
    result = capture(store, frame)
    reader = OfflineDataReader(tmp_path)
    facts = reader.read(snapshot_id=result["record"]["id"], normalizer=yf.NORMALIZER, table="facts").frame
    audit = reader.read(snapshot_id=result["record"]["id"], normalizer=yf.NORMALIZER, table="audit").frame
    assert facts.empty and len(audit) == 1 and audit.status.iloc[0] == "unavailable"
    assert store.read_payload(result["record"])["dataframe"]["shape"] == list(frame.shape)


def test_aware_source_label_keeps_its_local_calendar_date_and_timezone(tmp_path):
    frame = pd.DataFrame([[1]], columns=[pd.Timestamp("2000-12-31T23:30", tz="America/Toronto")])
    result = capture(SnapshotStore(tmp_path), frame)
    row = OfflineDataReader(tmp_path).read(snapshot_id=result["record"]["id"], normalizer=yf.NORMALIZER,
                                          table="facts").frame.iloc[0]
    assert row.period_end == pd.Timestamp("2000-12-31", tz="UTC")
    assert row.original_period_timezone == "America/Toronto" and "23:30" in row.source_period_label


def http_capture(store, *, body_symbol="SYNTH", request_symbol="SYNTH", statement="income", frequency="annual",
                 results=None, materialize=True):
    content = {"timeseries": {"result": [{"meta": {"symbol": [body_symbol], "type": ["annualNetIncome"]},
                                          "annualNetIncome": []}] if results is None else results, "error": None}}
    request = {"symbol": request_symbol, "statement": statement, "frequency": frequency}
    record = store.capture(yf.HTTP_PROVIDER, request, json.dumps(content).encode(),
                           observed_at="2001-04-02T10:00:00.500000+00:00")
    if materialize:
        store.publish_tables(record, yf.HTTP_NORMALIZER, {"audit": pd.DataFrame([{"status": "synthetic"}])},
                             provenance={"source_request": request, "source_provider": yf.HTTP_PROVIDER,
                                         "source_observed_at": record["observed_at"]})
    return record


def test_http_dependencies_prove_only_source_symbol_and_are_pinned_for_reader_replay(tmp_path, monkeypatch):
    offline(monkeypatch)
    store = SnapshotStore(tmp_path)
    http = http_capture(store)
    result = capture(store, http_records=[http])
    provenance = result["manifest"]["provenance"]
    assert provenance["source_symbol_verified"] is True
    assert provenance["issuer_identity_status"] == "unknown" and provenance["currency_status"] == "unknown"
    assert provenance["statement_scope"] == "unknown"
    assert provenance["http_statement_binding_basis"] == "collector_context_only_not_independent_source_semantics"
    assert len(provenance["input_snapshots"]) == 2 and len(provenance["input_manifests"]) == 1
    before = inventory(tmp_path)
    read = OfflineDataReader(tmp_path).read(snapshot_id=result["record"]["id"], normalizer=yf.NORMALIZER, table="facts")
    assert read.frame.source_symbol_verified.all() and len(read.metadata["verified_dependencies"]) == 2
    assert yf.replay_yfinance_statement(store, result["record"]) == result["manifest"]
    assert inventory(tmp_path) == before
    (tmp_path / http["raw_path"]).write_bytes(b"corrupt exact HTTP input")
    with pytest.raises(ValueError, match="hash|fingerprint"):
        OfflineDataReader(tmp_path).read(snapshot_id=result["record"]["id"], normalizer=yf.NORMALIZER, table="facts")
    with pytest.raises(ValueError, match="fingerprint"):
        yf.replay_yfinance_statement(store, result["record"])


def test_actual_http_adapter_and_dataframe_capture_keep_precision_disagreement_separate(tmp_path):
    from systematic_alpha_lab.data_pipeline.yahoo_timeseries import capture_yahoo_timeseries

    store = SnapshotStore(tmp_path)
    body = b'{"timeseries":{"result":[{"meta":{"symbol":["SYNTH"],"type":["annualNetIncome"]},"annualNetIncome":[{"asOfDate":"2000-12-31","reportedValue":{"raw":9007199254740993}}]}],"error":null}}'
    raw = capture_yahoo_timeseries(store, symbol="SYNTH", statement="income", body=body,
                                   observed_at="2001-04-02T10:00:00.500000+00:00")
    frame = pd.DataFrame([[float(9007199254740993)]], index=["NetIncome"], columns=[pd.Timestamp("2000-12-31")])
    derived = capture(store, frame, http_records=[raw["record"]])
    reader = OfflineDataReader(tmp_path)
    source = reader.read(snapshot_id=raw["record"]["id"], normalizer=yf.HTTP_NORMALIZER, table="facts").frame
    candidate = reader.read(snapshot_id=derived["record"]["id"], normalizer=yf.NORMALIZER, table="facts").frame
    assert source.source_value_json.iloc[0] == "9007199254740993"
    assert int(float.fromhex(candidate.value.iloc[0])) == 9007199254740992
    assert candidate.source_symbol_verified.all() and candidate.currency.isna().all()
    assert (tmp_path / raw["record"]["raw_path"]).read_bytes() == body
    assert yf.replay_yfinance_statement(store, derived["record"]) == derived["manifest"]


@pytest.mark.parametrize("results", [[], [{}], [{"meta": {}}]])
def test_missing_independent_http_symbol_evidence_never_upgrades_identity(tmp_path, results):
    store = SnapshotStore(tmp_path)
    result = capture(store, http_records=[http_capture(store, results=results, materialize=False)])
    assert result["manifest"]["provenance"]["source_symbol_verified"] is False
    assert result["manifest"]["provenance"]["http_raw_capture_status"] == "captured_dependencies"


@pytest.mark.parametrize("options", [
    {"body_symbol": "OTHER"}, {"request_symbol": "OTHER"}, {"statement": "cash-flow"}, {"frequency": "quarterly"},
])
def test_http_cross_source_symbol_method_and_frequency_conflicts_are_rejected(tmp_path, options):
    store = SnapshotStore(tmp_path)
    with pytest.raises(ValueError, match="dependency differs|symbol conflicts"):
        capture(store, http_records=[http_capture(store, **options)])


def test_duplicate_or_unregistered_http_pins_are_rejected(tmp_path):
    store = SnapshotStore(tmp_path)
    http = http_capture(store)
    with pytest.raises(ValueError, match="Duplicate"):
        capture(store, http_records=[http, http])
    changed = {**http, "raw_sha256": "f" * 64}
    with pytest.raises(ValueError, match="catalog pin"):
        capture(store, http_records=[changed])


def test_http_error_body_cannot_supply_independent_symbol_verification(tmp_path):
    store = SnapshotStore(tmp_path)
    raw = http_capture(store, materialize=False)
    body = store.read_payload(raw)
    body["timeseries"]["error"] = {"code": "synthetic_error"}
    record = store.capture(yf.HTTP_PROVIDER, json.loads(raw["request_json"]), json.dumps(body).encode(),
                           observed_at=raw["observed_at"])
    with pytest.raises(ValueError, match="successful financial"):
        capture(store, http_records=[record])


def test_prior_http_observation_cannot_be_attached_to_a_later_library_call(tmp_path):
    store = SnapshotStore(tmp_path)
    raw = http_capture(store, materialize=False)
    prior = store.capture(yf.HTTP_PROVIDER, json.loads(raw["request_json"]),
                          (tmp_path / raw["raw_path"]).read_bytes(), observed_at="2001-04-02T09:59:59+00:00")
    with pytest.raises(ValueError, match="request/time"):
        capture(store, http_records=[prior])
    # Replay must enforce the same interval even for an independently captured
    # and internally consistent DataFrame payload with a changed call start.
    captured = capture(store, http_records=[raw])
    content = store.read_payload(captured["record"])
    content["library_call_started_at"] = "2001-04-02T10:00:00.750000+00:00"
    fresh = store.capture(yf.PROVIDER, json.loads(captured["record"]["request_json"]),
                          json.dumps(content).encode(), observed_at=FINISH)
    with pytest.raises(ValueError, match="request/time"):
        yf.replay_yfinance_statement(store, fresh)


@pytest.mark.parametrize("issue", ["symbol", "method", "frequency", "version", "source_hash", "policy_hash",
                                  "response_layer", "observation", "shape", "extra_cell_field", "unknown_scalar"])
def test_replay_rejects_changed_payload_identity_versions_shape_and_scalar_contract(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    result = capture(store)
    content = store.read_payload(result["record"])
    if issue == "symbol":
        content["request"]["symbol"] = "OTHER"
    if issue == "method":
        content["request"]["function"] = "get_cash_flow"
    if issue == "frequency":
        content["request"]["frequency"] = "quarterly"
    if issue == "version":
        content["request"]["yfinance_version"] = "0.0.other"
    if issue == "source_hash":
        content["encoder_source_sha256"] = "f" * 64
    if issue == "policy_hash":
        content["policy_sha256"] = "f" * 64
    if issue == "response_layer":
        content["response_layer"] = "raw_http"
    if issue == "observation":
        content["library_call_finished_at"] = START
    if issue == "shape":
        content["dataframe"]["shape"][0] += 1
    if issue == "extra_cell_field":
        content["dataframe"]["data"][0][0]["extra"] = "ignored"
    if issue == "unknown_scalar":
        content["dataframe"]["data"][0][0]["kind"] = "unvalidated"
    fresh = store.capture(yf.PROVIDER, json.loads(result["record"]["request_json"]), json.dumps(content).encode(),
                           observed_at=FINISH)
    with pytest.raises(ValueError):
        yf.replay_yfinance_statement(store, fresh)
    assert store.dataset(fresh["id"], yf.NORMALIZER) is None


def test_request_frequency_and_code_drift_are_rejected_without_republishing(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    result = capture(store)
    before = inventory(tmp_path)
    monkeypatch.setattr(yf, "_source_sha", lambda: "f" * 64)
    with pytest.raises(ValueError, match="source code"):
        yf.replay_yfinance_statement(store, result["record"])
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("object_kind", ["raw", "table", "rehashed_table", "provenance", "missing_table"])
def test_corrupt_materializations_cannot_be_reused_even_with_rehashed_table_bytes(tmp_path, object_kind):
    store = SnapshotStore(tmp_path)
    result = capture(store)
    record, manifest = result["record"], result["manifest"]
    if object_kind == "raw":
        (tmp_path / record["raw_path"]).write_bytes(b"corrupt raw")
    elif object_kind == "table":
        (tmp_path / manifest["tables"]["facts"]["path"]).write_bytes(b"corrupt parquet")
    else:
        changed = deepcopy(manifest)
        if object_kind == "rehashed_table":
            path = tmp_path / changed["tables"]["facts"]["path"]
            frame = pd.read_parquet(path)
            frame.loc[0, "value"] = "9007199254740992"
            frame.to_parquet(path, index=False)
            changed["tables"]["facts"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        elif object_kind == "provenance":
            changed["provenance"]["normalizer_source_sha256"] = "f" * 64
        else:
            del changed["tables"]["audit"]
        with sqlite3.connect(store.catalog) as db:
            db.execute("UPDATE datasets SET manifest_json=? WHERE snapshot_id=? AND normalizer=?",
                       (json.dumps(changed), record["id"], yf.NORMALIZER))
    with pytest.raises(ValueError, match="fingerprint|hash|changed|exact typed"):
        yf.replay_yfinance_statement(store, record)


@pytest.mark.parametrize("changes", [
    {"method": "financials"}, {"symbol": "synth"}, {"yfinance_version": ""},
    {"contract_sha256": "not-a-digest"}, {"started_at": FINISH, "finished_at": START},
    {"started_at": "2001-04-02T10:00:00"},
])
def test_capture_requires_explicit_supported_request_version_and_aware_call_times(tmp_path, changes):
    store = SnapshotStore(tmp_path)
    before = inventory(tmp_path)
    with pytest.raises(ValueError):
        capture(store, **changes)
    assert inventory(tmp_path) == before


def test_invalid_or_future_source_period_labels_are_rejected_without_assuming_availability(tmp_path):
    store = SnapshotStore(tmp_path)
    for column in ("TTM", pd.Timestamp("2002-12-31")):
        with pytest.raises(ValueError, match="source date|exceeds"):
            capture(store, pd.DataFrame([[1]], columns=[column]))


def test_returned_manifest_policy_is_not_a_mutable_reference_to_module_policy(tmp_path):
    result = capture(SnapshotStore(tmp_path))
    policy = deepcopy(yf.POLICY)
    result["manifest"]["provenance"]["policy"]["eligibility"] = "mutated_by_caller"
    assert yf.POLICY == policy
