"""Synthetic frequency-explicit evidence, with networking and latest disabled."""
import hashlib
import json
import socket
import sqlite3
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline import yfinance_statement_snapshots_v2 as yf
from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

START = "2001-04-02T10:00:00+00:00"
OBSERVED = "2001-04-02T10:00:00.500000+00:00"
FINISH = "2001-04-02T10:00:01+00:00"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Network/latest attempted")
    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(SnapshotStore, "latest", denied)


def body(frequency="yearly", token="9007199254740993"):
    prefix = yf.FREQUENCIES[frequency]
    return ('{"timeseries":{"result":[{"meta":{"symbol":["SYNTH"],"type":["' + prefix + 'NetIncome"]},'
            '"timestamp":[978220800],"' + prefix + 'NetIncome":[{"asOfDate":"2000-12-31",'
            '"periodType":"' + ("12M" if frequency == "yearly" else "3M") + '","currencyCode":"USD",'
            '"reportedValue":{"raw":' + token + ',"fmt":"original"}}]}],"error":null}}').encode()


def capture_http(store, frequency="yearly", content=None, **changes):
    args = {"symbol": "SYNTH", "statement": "income", "frequency": frequency,
            "body": body(frequency) if content is None else content, "observed_at": OBSERVED}
    args.update(changes)
    return yf.capture_statement_http(store, **args)


def frame():
    return pd.DataFrame([[9007199254740993, -0.0], [None, pd.NA], [np.float32("nan"), float("inf")]],
                        index=["NetIncome", "NetIncome", "Other"],
                        columns=pd.DatetimeIndex(["2000-12-31", "2000-12-31"]), dtype=object)


def capture_frame(store, frequency="yearly", source_frame=None, **changes):
    args = {"symbol": "SYNTH", "method": "get_income_stmt", "frequency": frequency, "yfinance_version": "1.7.0",
            "started_at": START, "finished_at": FINISH, "http_records": ()}
    args.update(changes)
    return yf.capture_statement_frame(store, frame() if source_frame is None else source_frame, **args)


def read(store, captured, normalizer, table="facts"):
    return OfflineDataReader(store.root).read(snapshot_id=captured["record"]["id"], normalizer=normalizer, table=table)


def inventory(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("frequency", ["yearly", "quarterly"])
def test_raw_and_frame_exact_pins_roundtrip_through_reader_without_semantic_promotion(tmp_path, frequency):
    store = SnapshotStore(tmp_path)
    raw = capture_http(store, frequency, contract_sha256="a" * 64)
    derived = capture_frame(store, frequency, http_records=[raw["record"]], contract_sha256="a" * 64)
    assert (tmp_path / raw["record"]["raw_path"]).read_bytes() == body(frequency)
    source = read(store, raw, yf.HTTP_NORMALIZER).frame
    cells = read(store, derived, yf.FRAME_NORMALIZER).frame
    assert source.source_value_json.tolist() == ["9007199254740993"]
    assert source.source_value_type.tolist() == ["integer"]
    assert source.source_period_type.iloc[0] == ("12M" if frequency == "yearly" else "3M")
    assert source.period_start.isna().all() and cells.period_start.isna().all()
    assert source.currency.tolist() == ["USD"] and cells.currency.isna().all()
    assert cells.source_symbol_verified.all() and cells.available_at.isna().all() and cells.asset_id.isna().all()
    assert cells.amount_unit_status.eq("unknown").all() and cells.statement_scope.eq("unknown").all()
    assert cells.period_frequency_status.eq("requested_not_certified").all()
    assert cells.value.tolist()[:2] == ["9007199254740993", "-0x0.0p+0"]
    assert cells.source_row_position.tolist() == [0, 0, 1, 1, 2, 2]
    assert cells.source_column_position.tolist() == [0, 1] * 3
    audit = read(store, derived, yf.FRAME_NORMALIZER, "audit").frame.iloc[0]
    assert (audit.source_cells, audit.finite_numeric_cells, audit.missing_cells, audit.nonfinite_cells) == (6, 2, 3, 1)
    assert json.loads(audit.typed_dataframe_json) == yf.frame_v1.encode_dataframe(frame())
    provenance = derived["manifest"]["provenance"]
    assert provenance["helper_source_sha256"] == yf.HELPER_SHA256
    assert len(provenance["input_snapshots"]) == 2 and provenance["input_manifests"] == [raw["manifest"]]
    assert provenance["eligibility"] == "candidate_only_not_certified"
    for result, normalizer, replay in ((raw, yf.HTTP_NORMALIZER, yf.replay_statement_http),
                                        (derived, yf.FRAME_NORMALIZER, yf.replay_statement_frame)):
        request = json.loads(result["record"]["request_json"])
        receipt = {"snapshot_id": result["record"]["id"], "normalizer": normalizer,
                   "raw_sha256": result["record"]["raw_sha256"], "manifest": result["manifest"]}
        assert {item["table"] for item in OfflineDataReader(tmp_path).catalog(
            provider=result["record"]["provider"], request=request)} == {"facts", "audit"}
        before = inventory(tmp_path)
        assert replay(store, result["record"]) == receipt["manifest"]
        assert inventory(tmp_path) == before


def test_frequency_and_schema_are_part_of_request_identity_not_old_annual_request(tmp_path):
    store = SnapshotStore(tmp_path)
    annual, quarterly = capture_http(store), capture_http(store, "quarterly")
    assert annual["record"]["request_id"] != quarterly["record"]["request_id"]
    request = json.loads(annual["record"]["request_json"])
    assert request["schema"] == yf.HTTP_SCHEMA and request["frequency"] == "yearly"
    assert request != yf.raw_v1._request("SYNTH", "income")
    a, q = capture_frame(store), capture_frame(store, "quarterly")
    assert a["record"]["request_id"] != q["record"]["request_id"]
    assert json.loads(a["record"]["request_json"])["schema"] == yf.FRAME_SCHEMA


@pytest.mark.parametrize("frequency", ["yearly", "quarterly"])
@pytest.mark.parametrize("token,kind", [("1.2300", "float"), ("1e-30", "float"), ("-0.0", "float"),
                                        ("-0", "integer"), ("123456789012345678901234567890", "integer")])
def test_http_numeric_lexemes_and_entire_source_item_are_exact(tmp_path, frequency, token, kind):
    store = SnapshotStore(tmp_path)
    result = capture_http(store, frequency, body(frequency, token))
    row = read(store, result, yf.HTTP_NORMALIZER).frame.iloc[0]
    assert row.source_value_json == token and row.source_value_type == kind
    assert '"raw":' + token in row.source_item_json
    assert '"fmt":"original"' in row.source_item_json


def test_float_library_precision_loss_is_separate_from_original_raw_integer(tmp_path):
    store = SnapshotStore(tmp_path)
    raw = capture_http(store, "quarterly")
    source_frame = pd.DataFrame([[float(9007199254740993)]], index=["NetIncome"], columns=[pd.Timestamp("2000-12-31")])
    derived = capture_frame(store, "quarterly", source_frame, http_records=[raw["record"]])
    assert read(store, raw, yf.HTTP_NORMALIZER).frame.source_value_json.iloc[0] == "9007199254740993"
    row = read(store, derived, yf.FRAME_NORMALIZER).frame.iloc[0]
    assert row.value_kind == "np_float64" and int(float.fromhex(row.value)) == 9007199254740992


@pytest.mark.parametrize("frequency", ["yearly", "quarterly"])
@pytest.mark.parametrize("case", ["empty", "unknown", "meta_only", "metric_empty"])
def test_empty_and_metadata_only_capture_audit_without_fabricating_observations(tmp_path, frequency, case):
    prefix = yf.FREQUENCIES[frequency]
    results = [] if case == "empty" else None if case == "unknown" else [
        {"meta": {"symbol": ["SYNTH"], "type": [prefix + "NetIncome"]},
         **({prefix + "NetIncome": []} if case == "metric_empty" else {})}]
    store = SnapshotStore(tmp_path)
    result = capture_http(store, frequency, json.dumps({"timeseries": {"result": results, "error": None}}).encode())
    assert read(store, result, yf.HTTP_NORMALIZER).frame.empty
    audit = read(store, result, yf.HTTP_NORMALIZER, "audit").frame
    assert len(audit) == 1 and audit.source_item_count.iloc[0] == 0 and audit.numeric_item_count.iloc[0] == 0
    assert result["manifest"]["provenance"]["statement_completeness"] == "not_certified"


@pytest.mark.parametrize("source_frame", [pd.DataFrame(), pd.DataFrame(index=["metric"]),
                                         pd.DataFrame(columns=[pd.Timestamp("2000-12-31")])])
def test_empty_frame_preserves_shape_and_unavailable_audit(tmp_path, source_frame):
    store = SnapshotStore(tmp_path)
    captured = capture_frame(store, "quarterly", source_frame)
    assert read(store, captured, yf.FRAME_NORMALIZER).frame.empty
    audit = read(store, captured, yf.FRAME_NORMALIZER, "audit").frame.iloc[0]
    assert audit.status == "unavailable"
    assert json.loads(audit.typed_dataframe_json)["shape"] == list(source_frame.shape)
    assert captured["manifest"]["provenance"]["source_symbol_verified"] is False


def test_missing_values_and_metadata_remain_unknown_and_period_type_does_not_supply_start(tmp_path):
    content = json.loads(body("quarterly"))
    item = content["timeseries"]["result"][0]["quarterlyNetIncome"][0]
    item.pop("asOfDate"); item.pop("currencyCode"); item.pop("reportedValue"); item["periodType"] = "TTM"
    store = SnapshotStore(tmp_path)
    raw = capture_http(store, "quarterly", json.dumps(content).encode())
    row = read(store, raw, yf.HTTP_NORMALIZER).frame.iloc[0]
    assert row.source_period_type == "TTM" and pd.isna(row.period_start) and pd.isna(row.period_end)
    assert pd.isna(row.currency) and row.source_value_type == "absent" and row.value_status == "unavailable"
    candidate = capture_frame(store, "quarterly", pd.DataFrame([[0, None]], columns=["TTM", pd.NaT], dtype=object))
    facts = read(store, candidate, yf.FRAME_NORMALIZER).frame
    assert facts.period_end.isna().all() and facts.period_end_status.eq("unknown").all()
    assert facts.value_kind.tolist() == ["int", "none"]


@pytest.mark.parametrize("issue", ["symbol", "prefix", "mixed", "duplicate_metric", "duplicate_date", "duplicate_json",
                                  "actual_field", "bool_value", "nonfinite", "provider_error", "future_date"])
def test_raw_identity_frequency_duplicates_and_invalid_numeric_contract_reject_before_capture(tmp_path, issue):
    content = json.loads(body("quarterly"))
    result = content["timeseries"]["result"][0]
    if issue == "symbol": result["meta"]["symbol"] = ["OTHER"]
    if issue == "prefix": result["meta"]["type"] = ["annualNetIncome"]
    if issue == "mixed": result["annualNetIncome"] = []
    if issue == "duplicate_metric": content["timeseries"]["result"].append(deepcopy(result))
    if issue == "duplicate_date": result["quarterlyNetIncome"].append(deepcopy(result["quarterlyNetIncome"][0]))
    if issue == "actual_field": result["quarterlyAssets"] = result.pop("quarterlyNetIncome")
    if issue == "bool_value": result["quarterlyNetIncome"][0]["reportedValue"]["raw"] = True
    if issue == "provider_error": content["timeseries"]["error"] = {"code": "synthetic"}
    if issue == "future_date": result["quarterlyNetIncome"][0]["asOfDate"] = "2002-01-01"
    encoded = json.dumps(content).encode()
    if issue == "duplicate_json": encoded = encoded.replace(b'"error": null', b'"error": null,"error": null')
    if issue == "nonfinite": encoded = encoded.replace(b"9007199254740993", b"NaN")
    store = SnapshotStore(tmp_path)
    before = inventory(tmp_path)
    with pytest.raises(ValueError): capture_http(store, "quarterly", encoded)
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("issue", ["symbol", "statement", "frequency", "contract", "before", "after", "duplicate", "version"])
def test_frame_dependency_must_match_exact_same_call_company_statement_frequency_and_contract(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    frequency = "yearly" if issue == "frequency" else "quarterly"
    kwargs = {"symbol": "OTHER", "body": body(frequency).replace(b"SYNTH", b"OTHER")} if issue == "symbol" else {}
    if issue == "statement": kwargs["statement"] = "cash-flow"
    if issue == "contract": kwargs["contract_sha256"] = "b" * 64
    if issue == "before": kwargs["observed_at"] = "2001-04-02T09:59:59+00:00"
    if issue == "after": kwargs["observed_at"] = "2001-04-02T10:00:02+00:00"
    raw = capture_http(store, frequency, **kwargs)
    records = [raw["record"]] * (2 if issue == "duplicate" else 1)
    with pytest.raises(ValueError):
        capture_frame(store, "quarterly", http_records=records, contract_sha256="a" * 64 if issue == "contract" else None,
                      yfinance_version="2.0.0" if issue == "version" else "1.7.0")


def test_typed_library_values_do_not_promote_bool_strings_zero_or_missing_and_keep_timezone(tmp_path):
    values = [False, True, 0, -0.0, "None", "001.00", pd.NaT, None, pd.NA, float("nan")]
    source = pd.DataFrame([[value] for value in values], index=["same"] * len(values), dtype=object,
                          columns=[pd.Timestamp("2000-12-31T23:30", tz="America/Toronto")])
    store = SnapshotStore(tmp_path)
    captured = capture_frame(store, "quarterly", source)
    facts = read(store, captured, yf.FRAME_NORMALIZER).frame
    for position, value in enumerate(values):
        encoded = yf.frame_v1.encode_scalar(value)
        assert facts.value_kind.iloc[position] == encoded["kind"] and facts.value.iloc[position] == encoded["value"]
    assert facts.value_status.tolist() == ["nonnumeric", "nonnumeric", "finite_numeric", "finite_numeric",
                                           "nonnumeric", "nonnumeric", "missing", "missing", "missing", "missing"]
    assert facts.period_end.eq(pd.Timestamp("2000-12-31", tz="UTC")).all()
    assert facts.original_period_timezone.eq("America/Toronto").all()


def test_new_frame_may_not_attach_old_annual_schema_or_wrong_source_record_pin(tmp_path):
    store = SnapshotStore(tmp_path)
    old = yf.raw_v1.capture_yahoo_timeseries(store, symbol="SYNTH", statement="income", body=body(), observed_at=OBSERVED)
    with pytest.raises(ValueError, match="schema|frequency"):
        capture_frame(store, http_records=[old["record"]])
    raw = capture_http(store)
    changed = {**raw["record"], "raw_sha256": "f" * 64}
    with pytest.raises(ValueError, match="catalog pin"):
        capture_frame(store, http_records=[changed])


def test_raw_dependency_tamper_is_detected_by_offline_reader_and_frame_replay(tmp_path):
    store = SnapshotStore(tmp_path)
    raw = capture_http(store)
    derived = capture_frame(store, http_records=[raw["record"]])
    (tmp_path / raw["record"]["raw_path"]).write_bytes(b"corrupt raw dependency")
    with pytest.raises(ValueError, match="hash|fingerprint"):
        read(store, derived, yf.FRAME_NORMALIZER)
    with pytest.raises(ValueError, match="fingerprint"):
        yf.replay_statement_frame(store, derived["record"])


@pytest.mark.parametrize("layer", ["raw", "frame"])
def test_own_source_hash_and_frozen_helper_changes_reject_replay_without_writes(tmp_path, monkeypatch, layer):
    store = SnapshotStore(tmp_path)
    result = capture_http(store) if layer == "raw" else capture_frame(store)
    replay = yf.replay_statement_http if layer == "raw" else yf.replay_statement_frame
    before = inventory(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(yf, "_source_sha", lambda: "f" * 64)
        with pytest.raises(ValueError, match="source code"): replay(store, result["record"])
    with monkeypatch.context() as patch:
        patch.setattr(yf, "HELPER_SHA256", {"wrong": "f" * 64})
        with pytest.raises(ValueError, match="helper source"): replay(store, result["record"])
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("layer", ["raw", "frame"])
@pytest.mark.parametrize("issue", ["raw_bytes", "table_bytes", "rehashed_table", "provenance", "missing_table"])
def test_corrupt_or_rehashed_materialization_cannot_be_reused(tmp_path, layer, issue):
    store = SnapshotStore(tmp_path)
    result = capture_http(store) if layer == "raw" else capture_frame(store)
    replay = yf.replay_statement_http if layer == "raw" else yf.replay_statement_frame
    normalizer = yf.HTTP_NORMALIZER if layer == "raw" else yf.FRAME_NORMALIZER
    record, manifest = result["record"], deepcopy(result["manifest"])
    if issue == "raw_bytes": (tmp_path / record["raw_path"]).write_bytes(b"tamper")
    elif issue == "table_bytes": (tmp_path / manifest["tables"]["facts"]["path"]).write_bytes(b"tamper")
    else:
        if issue == "rehashed_table":
            path = tmp_path / manifest["tables"]["facts"]["path"]
            data = pd.read_parquet(path)
            data.loc[0, "source_value_json" if layer == "raw" else "value"] = "123"
            data.to_parquet(path, index=False)
            manifest["tables"]["facts"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        if issue == "provenance": manifest["provenance"]["normalizer_source_sha256"] = "f" * 64
        if issue == "missing_table": del manifest["tables"]["audit"]
        with sqlite3.connect(store.catalog) as db:
            db.execute("UPDATE datasets SET manifest_json=? WHERE snapshot_id=? AND normalizer=?",
                       (json.dumps(manifest), record["id"], normalizer))
    with pytest.raises(ValueError): replay(store, record)


def test_frame_replay_rechecks_same_call_lower_bound_even_with_consistently_rehashed_capture(tmp_path):
    store = SnapshotStore(tmp_path)
    raw = capture_http(store, "quarterly")
    captured = capture_frame(store, "quarterly", http_records=[raw["record"]])
    content = store.read_payload(captured["record"])
    content["library_call_started_at"] = "2001-04-02T10:00:00.750000+00:00"
    fresh = store.capture(yf.FRAME_PROVIDER, json.loads(captured["record"]["request_json"]),
                          json.dumps(content).encode(), observed_at=FINISH)
    with pytest.raises(ValueError, match="request/time"): yf.replay_statement_frame(store, fresh)


@pytest.mark.parametrize("issue", ["request", "helper", "source", "policy", "shape", "scalar", "finish"])
def test_frame_payload_contract_is_strict_before_publication(tmp_path, issue):
    store = SnapshotStore(tmp_path)
    captured = capture_frame(store)
    content = store.read_payload(captured["record"])
    if issue == "request": content["request"]["frequency"] = "quarterly"
    if issue == "helper": content["helper_source_sha256"] = {}
    if issue == "source": content["normalizer_source_sha256"] = "f" * 64
    if issue == "policy": content["policy_sha256"] = "f" * 64
    if issue == "shape": content["dataframe"]["shape"][0] += 1
    if issue == "scalar": content["dataframe"]["data"][0][0] = {"kind": "int", "value": "001"}
    if issue == "finish": content["library_call_finished_at"] = START
    fresh = store.capture(yf.FRAME_PROVIDER, json.loads(captured["record"]["request_json"]),
                          json.dumps(content).encode(), observed_at=FINISH)
    with pytest.raises(ValueError): yf.replay_statement_frame(store, fresh)
    assert store.dataset(fresh["id"], yf.FRAME_NORMALIZER) is None
