"""Synthetic raw Yahoo timeseries: no company requests, yfinance or credentials."""
import hashlib
import json
import socket
from copy import deepcopy

import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline import yahoo_timeseries as yahoo
from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

NOW = "2026-10-23T12:00:00Z"
SYMBOL = "SYNTH"


def payload():
    return {"timeseries": {"result": [{
        "meta": {"symbol": [SYMBOL], "type": ["annualNetIncome"]}, "timestamp": [1735603200, 1703980800],
        "annualNetIncome": [
            {"asOfDate": "2024-12-31", "periodType": "12M", "currencyCode": "USD",
             "reportedValue": {"raw": 9007199254740993, "fmt": "source display"}},
            {"asOfDate": "2023-12-31", "periodType": "12M", "currencyCode": "EUR",
             "reportedValue": {"raw": None}},
        ],
    }], "error": None}}


def capture(store, content=None, **kwargs):
    return yahoo.capture_yahoo_timeseries(store, symbol=SYMBOL, statement="income", observed_at=NOW,
                                          body=json.dumps(payload() if content is None else content).encode(), **kwargs)


def read(store, result, table="facts"):
    return OfflineDataReader(store.root).read(snapshot_id=result["record"]["id"],
                                              normalizer=yahoo.NORMALIZER, table=table)


def inventory(root):
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def test_original_bytes_exact_large_integer_and_null_source_types_survive_offline(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    body = json.dumps(payload(), indent=3).encode() + b"\n"
    result = yahoo.capture_yahoo_timeseries(store, symbol=SYMBOL, statement="income", observed_at=NOW, body=body,
                                            contract_sha256="a" * 64)
    record, manifest = result["record"], result["manifest"]
    assert (store.root / record["raw_path"]).read_bytes() == body
    assert record["provider"] == yahoo.PROVIDER and record["raw_sha256"] == hashlib.sha256(body).hexdigest()
    request = json.loads(record["request_json"])
    assert request["frequency"] == "annual" and request["contract_sha256"] == "a" * 64
    assert request["adapter_version"] == "1.7.0"
    before = inventory(tmp_path)
    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("Network attempted"))
    monkeypatch.setattr(SnapshotStore, "latest", lambda *a, **k: pytest.fail("Latest selection attempted"))
    frame = read(store, result).frame
    assert frame.source_value_json.tolist() == ["9007199254740993", "null"]
    assert frame.source_value_type.tolist() == ["integer", "null"]
    assert frame.currency.tolist() == ["USD", "EUR"]
    assert frame.source_period_type.tolist() == ["12M", "12M"]
    assert frame.period_end.tolist() == [pd.Timestamp("2024-12-31", tz="UTC"), pd.Timestamp("2023-12-31", tz="UTC")]
    assert frame.period_start.isna().all() and frame.available_at.isna().all() and frame.asset_id.isna().all()
    assert frame.flow_basis.eq("unverified").all() and frame.amount_unit_status.eq("unverified").all()
    assert json.loads(frame.source_item_json.iloc[0]) == payload()["timeseries"]["result"][0]["annualNetIncome"][0]
    assert read(store, result, "audit").frame.numeric_item_count.tolist() == [1]
    assert manifest["provenance"]["numeric_fact_rows"] == 1
    assert yahoo.replay_yahoo_timeseries(store, record) == manifest
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("token,kind", [("1.2300", "float"), ("1e-30", "float"), ("-0.0", "float"),
                                        ("-0", "integer"), ("123456789012345678901234567890", "integer")])
def test_numeric_json_lexemes_are_not_converted_to_float_or_reserialized(tmp_path, token, kind):
    body = json.dumps(payload()).replace('9007199254740993', token).encode()
    store = SnapshotStore(tmp_path)
    result = yahoo.capture_yahoo_timeseries(store, symbol=SYMBOL, statement="income", observed_at=NOW, body=body)
    row = read(store, result).frame.iloc[0]
    assert row.source_value_json == token and row.source_value_type == kind
    assert '"raw":' + token in row.source_item_json


@pytest.mark.parametrize("statement", yahoo.STATEMENTS)
def test_partial_metric_chunks_and_source_statement_labels_are_not_full_coverage(tmp_path, statement):
    store = SnapshotStore(tmp_path)
    result = yahoo.capture_yahoo_timeseries(store, symbol=SYMBOL, statement=statement, observed_at=NOW,
                                            body=json.dumps(payload()).encode())
    assert read(store, result).frame.source_statement.eq(statement).all()
    assert result["manifest"]["provenance"]["statement_completeness"] == "not_certified_response_chunk_only"
    assert result["manifest"]["provenance"]["eligibility"] == "not_certified"


@pytest.mark.parametrize("mode", ["missing", "null", "invalid_format"])
def test_metadata_unknown_or_nonstandard_values_are_not_imputed(tmp_path, mode):
    data = payload(); point = data["timeseries"]["result"][0]["annualNetIncome"][0]
    for name in ("currencyCode", "periodType", "asOfDate"):
        if mode == "missing": point.pop(name)
        elif mode == "null": point[name] = None
    if mode == "invalid_format": point.update(currencyCode="usd", periodType="3M")
    store = SnapshotStore(tmp_path); result = capture(store, data); row = read(store, result).frame.iloc[0]
    if mode == "invalid_format":
        assert row.currency == "usd" and row.source_period_type == "3M"
        assert row.currency_status == "unrecognized_source_format"
    else:
        assert pd.isna(row.currency) and pd.isna(row.period_end) and row.period_end_status == "unknown"
        assert pd.isna(row.source_currency_json) if mode == "missing" else row.source_currency_json == "null"


@pytest.mark.parametrize("result", [[], None])
def test_unavailable_results_retain_raw_and_audit_without_claiming_statement_data(tmp_path, result):
    store = SnapshotStore(tmp_path); data = {"timeseries": {"result": result, "error": None}}
    captured = capture(store, data)
    assert read(store, captured).frame.empty
    audit = read(store, captured, "audit").frame
    assert len(audit) == 1 and not audit.source_symbol_verified.any()
    assert captured["manifest"]["provenance"]["numeric_fact_rows"] == 0
    assert not captured["manifest"]["provenance"]["source_symbol_verified"]


@pytest.mark.parametrize("issue", ["symbol", "multi_symbol", "type", "multi_type", "actual_metric", "duplicate_metric",
                                  "duplicate_period", "timestamp", "duplicate_timestamp", "result_shape", "item_shape",
                                  "date", "future", "currency_type", "numeric_currency", "numeric_period_type",
                                  "raw_bool", "raw_list", "raw_string", "error"])
def test_mismatches_and_ambiguous_or_unsupported_source_shapes_fail_before_capture(tmp_path, issue):
    data = payload(); result = data["timeseries"]["result"][0]; point = result["annualNetIncome"][0]
    if issue == "symbol": result["meta"]["symbol"] = "OTHER"
    if issue == "multi_symbol": result["meta"]["symbol"].append("OTHER")
    if issue == "type": result["meta"]["type"] = ["quarterlyNetIncome"]
    if issue == "multi_type": result["meta"]["type"].append("annualAssets")
    if issue == "actual_metric": result["annualAssets"] = result.pop("annualNetIncome")
    if issue == "duplicate_metric": data["timeseries"]["result"].append(deepcopy(result))
    if issue == "duplicate_period": result["annualNetIncome"][1]["asOfDate"] = point["asOfDate"]
    if issue == "timestamp": result["timestamp"] = [True]
    if issue == "duplicate_timestamp": result["timestamp"] *= 2
    if issue == "result_shape": data["timeseries"]["result"] = {}
    if issue == "item_shape": result["annualNetIncome"] = [1]
    if issue == "date": point["asOfDate"] = "not-a-date"
    if issue == "future": point["asOfDate"] = "2027-12-31"
    if issue == "currency_type": point["currencyCode"] = ["USD"]
    if issue == "numeric_currency": point["currencyCode"] = 123
    if issue == "numeric_period_type": point["periodType"] = 12
    if issue == "raw_bool": point["reportedValue"]["raw"] = True
    if issue == "raw_list": point["reportedValue"]["raw"] = [1]
    if issue == "raw_string": point["reportedValue"]["raw"] = "1"
    if issue == "error": data["timeseries"]["error"] = {"description": "synthetic failure"}
    store = SnapshotStore(tmp_path); before = inventory(tmp_path)
    with pytest.raises(ValueError): capture(store, data)
    assert inventory(tmp_path) == before


def test_singleton_strings_missing_raw_and_missing_metric_arrays_are_auditable(tmp_path):
    data = payload(); result = data["timeseries"]["result"][0]
    result["meta"] = {"symbol": SYMBOL, "type": "annualNetIncome"}
    result["annualNetIncome"][0]["reportedValue"].pop("raw")
    store = SnapshotStore(tmp_path); captured = capture(store, data)
    row = read(store, captured).frame.iloc[0]
    assert row.source_value_type == "absent" and pd.isna(row.source_value_json) and row.value_status == "unavailable"
    result.pop("annualNetIncome")
    second = capture(store, data)
    assert read(store, second).frame.empty and read(store, second, "audit").frame.status.tolist() == ["metric_items_unknown"]


@pytest.mark.parametrize("corrupt", ["duplicate_json", "nonfinite"])
def test_invalid_json_rejected_without_source_registration(tmp_path, corrupt):
    body = json.dumps(payload()).encode()
    body = body.replace(b'"raw": 9007199254740993', b'"raw": 1, "raw": 2' if corrupt == "duplicate_json" else b'"raw": NaN')
    store = SnapshotStore(tmp_path); before = inventory(tmp_path)
    with pytest.raises(ValueError):
        yahoo.capture_yahoo_timeseries(store, symbol=SYMBOL, statement="income", observed_at=NOW, body=body)
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("change", ["record", "raw", "table", "source"])
def test_exact_source_and_normalizer_pins_are_checked_on_replay(tmp_path, monkeypatch, change):
    store = SnapshotStore(tmp_path / "data"); captured = capture(store); record = captured["record"]
    if change == "record": record = {**record, "observed_at": "2026-10-22T12:00:00+00:00"}
    if change == "raw": (store.root / record["raw_path"]).write_bytes(b"{}")
    if change == "table": (store.root / captured["manifest"]["tables"]["facts"]["path"]).write_bytes(b"bad")
    if change == "source":
        other = tmp_path / "changed.py"; other.write_text("# synthetic different parser source")
        monkeypatch.setattr(yahoo, "__file__", str(other))
    with pytest.raises(ValueError): yahoo.replay_yahoo_timeseries(store, record)


@pytest.mark.parametrize("argument,value", [("symbol", "../bad"), ("statement", "quarterly"),
                                           ("contract_sha256", "not-a-digest")])
def test_explicit_request_validation(tmp_path, argument, value):
    args = {"symbol": SYMBOL, "statement": "income", "body": json.dumps(payload()).encode(), "observed_at": NOW}
    args[argument] = value
    with pytest.raises(ValueError): yahoo.capture_yahoo_timeseries(SnapshotStore(tmp_path), **args)
