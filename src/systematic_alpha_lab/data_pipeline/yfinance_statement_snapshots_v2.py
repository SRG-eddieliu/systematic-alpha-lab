"""Offline, frequency-explicit Yahoo HTTP and library-frame candidate evidence.

The frozen v1 helper files are dependencies, not upgraded normalizers. Requests
do not establish fiscal duration, complete statements, issuer scope or units.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from . import yahoo_timeseries as raw_v1
from . import yfinance_snapshots as frame_v1
from .offline_reader import OfflineDataReader
from .snapshot_store import SnapshotStore, utc_time

HTTP_PROVIDER = raw_v1.PROVIDER
FRAME_PROVIDER = frame_v1.PROVIDER
HTTP_NORMALIZER = "yf_statement_http_v2"
FRAME_NORMALIZER = "yf_statement_frames_v2"
HTTP_SCHEMA = "yf_statement_http_capture_v2"
FRAME_SCHEMA = "yf_statement_frame_capture_v2"
FREQUENCIES = {"yearly": "annual", "quarterly": "quarterly"}
METHODS = dict(frame_v1.METHODS)
HELPER_SHA256 = {
    "yahoo_timeseries.py": "9e4ae694d712f00d7e49ebde8702b163fb7792c657feab03272c325406cd6093",
    "yfinance_snapshots.py": "c97cd5cd8219d7a0d56439558f797878dcb01da5ef8eea0e5bc99e6e294f0e71",
}
POLICY = {
    "http_values": "original_json_number_lexeme_and_type",
    "frame_values": "typed_scalar_strings_not_original_http_precision",
    "period_basis": "source_calendar_label_UTC_not_availability",
    "frequency_basis": "explicit_request_not_fiscal_duration_certification",
    "statement_binding": "collector_context_not_independent_statement_semantics",
    "coverage": "response_chunk_or_library_frame_not_complete_statements",
    "metadata": "unknown_without_independent_evidence",
    "eligibility": "candidate_only_not_certified",
}
_RECORD_FIELDS = ("id", "request_id", "provider", "request_json", "observed_at", "raw_sha256", "raw_path")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _source_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _helpers():
    actual = {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
              for module in (raw_v1, frame_v1)}
    if actual != HELPER_SHA256:
        raise ValueError("Frozen helper source changed; use a new version with reviewed helper pins")
    return actual


def _base_request(symbol, statement, frequency, contract_sha256):
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol):
        raise ValueError("Require an explicit Yahoo symbol")
    if not isinstance(statement, str) or statement not in raw_v1.STATEMENTS:
        raise ValueError("Unsupported explicit statement")
    if not isinstance(frequency, str) or frequency not in FREQUENCIES:
        raise ValueError("Require explicit yearly or quarterly frequency")
    if contract_sha256 is not None and (not isinstance(contract_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", contract_sha256
    )):
        raise ValueError("Invalid optional contract fingerprint")
    return {"symbol": symbol, "statement": statement, "frequency": frequency,
            "contract_sha256": contract_sha256, "normalizer_source_sha256": _source_sha(),
            "helper_source_sha256": _helpers()}


def _http_request(symbol, statement, frequency, contract_sha256):
    return {**_base_request(symbol, statement, frequency, contract_sha256), "schema": HTTP_SCHEMA,
            "adapter": "yfinance", "adapter_version": raw_v1.ADAPTER_VERSION,
            "adapter_source_sha256": raw_v1.ADAPTER_SOURCE_SHA256}


def _frame_request(symbol, method, frequency, version, contract_sha256):
    if not isinstance(method, str) or method not in METHODS:
        raise ValueError("Require an explicit supported library method")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}", version):
        raise ValueError("Require the actual library version")
    return {**_base_request(symbol, METHODS[method], frequency, contract_sha256), "schema": FRAME_SCHEMA,
            "function": method, "yfinance_version": version, "as_dict": False, "pretty": False}


def _registered(store, supplied, provider):
    if not isinstance(supplied, dict) or "id" not in supplied:
        raise ValueError("Require an exact registered record")
    record = store.get(supplied["id"])
    if record is None or any(supplied.get(name) != record[name] for name in _RECORD_FIELDS):
        raise ValueError("Source differs from its exact catalog pin")
    request = frame_v1._strict_json(record["request_json"])
    if record["provider"] != provider or record["request_id"] != SnapshotStore.request_id(provider, request):
        raise ValueError("Source provider/request identity differs")
    relative = Path(record["raw_path"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in record["raw_path"]:
        raise ValueError("Raw source escapes the data root")
    path = (store.root / relative).resolve(strict=True)
    if not path.is_relative_to(store.root) or not path.is_file():
        raise ValueError("Raw source escapes the data root")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != record["raw_sha256"]:
        raise ValueError("Raw source fingerprint differs")
    return record, request, body


def _validate_http_request(request):
    if not isinstance(request, dict) or request != _http_request(
        request.get("symbol"), request.get("statement"), request.get("frequency"), request.get("contract_sha256")
    ):
        raise ValueError("HTTP request schema/frequency/source code differs")


def _identity(tables, record, request, provider, normalizer):
    for frame in tables.values():
        for name, value in {
            "provider": provider, "symbol": request["symbol"], "snapshot_id": record["id"],
            "normalizer": normalizer, "source_statement": request["statement"],
            "source_statement_status": "collector_context_only_not_independent_source_semantics",
            "source_frequency": request["frequency"], "period_frequency_status": "requested_not_certified",
            "statement_scope": "unknown", "amount_unit_status": "unknown", "flow_basis": "unknown",
            "identifier_basis": "provider_symbol_issuer_unverified", "eligibility": POLICY["eligibility"],
        }.items():
            frame[name] = pd.Series(value, index=frame.index, dtype="string")
        frame["observed_at"] = pd.Series(pd.Timestamp(record["observed_at"]), index=frame.index,
                                        dtype="datetime64[ns, UTC]")
        frame["available_at"] = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
        frame["asset_id"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    return tables


def _http_tables(body, request, record):
    payload = raw_v1._parse(body)
    response = payload.get("timeseries") if isinstance(payload, dict) else None
    if not isinstance(response, dict) or response.get("error") is not None:
        raise ValueError("Require a successful Yahoo timeseries response")
    results = response.get("result")
    if results is not None and not isinstance(results, list):
        raise ValueError("Require a Yahoo result array")
    observed, prefix = pd.Timestamp(record["observed_at"]), FREQUENCIES[request["frequency"]]
    rows, audits, metrics = [], [], set()
    if not results:
        audits.append({"source_result_index": -1, "source_metric": None, "source_meta_json": None,
                       "source_timestamp_json": None, "source_item_count": 0, "numeric_item_count": 0,
                       "source_symbol_verified": False,
                       "status": "empty_result" if results == [] else "result_unknown"})
    for position, result in enumerate(results or []):
        if not isinstance(result, dict) or not isinstance(result.get("meta"), dict):
            raise TypeError("Require explicit Yahoo metadata")
        meta = result["meta"]
        if raw_v1._singleton(meta.get("symbol"), "symbol") != request["symbol"]:
            raise ValueError("Yahoo response symbol differs from request")
        metric = raw_v1._singleton(meta.get("type"), "metric type")
        if not re.fullmatch(prefix + r"[A-Za-z][A-Za-z0-9]{0,159}", metric) or metric in metrics:
            raise ValueError("Wrong frequency prefix or duplicate metric")
        metrics.add(metric)
        if set(result) - {"meta", "timestamp", metric}:
            raise ValueError("Yahoo metric fields conflict with metadata/frequency")
        timestamps = result.get("timestamp")
        if timestamps is not None and (not isinstance(timestamps, list) or any(
            not isinstance(value, raw_v1._Integer) for value in timestamps
        ) or len(set(timestamps)) != len(timestamps)):
            raise ValueError("Invalid or duplicate source timestamps")
        items = result.get(metric)
        if items is not None and not isinstance(items, list):
            raise ValueError("Require a metric item array")
        periods, numeric = set(), 0
        for item_position, item in enumerate(items or []):
            if not isinstance(item, dict):
                raise TypeError("Require a financial item object")
            period, date_json, period_status = raw_v1._period(item, observed)
            key = None if pd.isna(period) else period.isoformat()
            if key in periods:
                raise ValueError("Duplicate metric/period; do not deduplicate")
            periods.add(key)
            value, kind, status = raw_v1._value(item)
            currency, currency_json = raw_v1._metadata(item, "currencyCode")
            source_period, source_period_json = raw_v1._metadata(item, "periodType")
            numeric += status == "reported_numeric"
            rows.append({"source_result_index": position, "source_item_index": item_position,
                         "source_metric": metric, "source_item_json": raw_v1._json(item),
                         "source_value_json": value, "source_value_type": kind, "value_status": status,
                         "period_end": period, "period_end_status": period_status,
                         "source_as_of_date_json": date_json, "currency": currency,
                         "source_currency_json": currency_json,
                         "currency_status": "unknown" if currency is None else "source_label_unverified",
                         "source_period_type": source_period, "source_period_type_json": source_period_json,
                         "source_period_type_status": "unknown" if source_period is None else "source_label_unverified"})
        audits.append({"source_result_index": position, "source_metric": metric,
                       "source_meta_json": raw_v1._json(meta),
                       "source_timestamp_json": raw_v1._json(timestamps) if "timestamp" in result else None,
                       "source_item_count": len(items or []), "numeric_item_count": numeric,
                       "source_symbol_verified": True,
                       "status": "observed_cells" if items else "metric_empty" if items == [] else "metric_items_unknown"})
    columns = ["source_result_index", "source_item_index", "source_metric", "source_item_json", "source_value_json",
               "source_value_type", "value_status", "period_end", "period_end_status", "source_as_of_date_json",
               "currency", "source_currency_json", "currency_status", "source_period_type", "source_period_type_json",
               "source_period_type_status"]
    facts = pd.DataFrame(rows, columns=columns)
    for name in ("source_result_index", "source_item_index"):
        facts[name] = facts[name].astype("int64")
    facts["period_end"] = pd.to_datetime(facts.period_end, utc=True)
    facts["source_symbol_verified"] = pd.Series(True, index=facts.index, dtype="bool")
    facts["period_start"] = pd.Series(pd.NaT, index=facts.index, dtype="datetime64[ns, UTC]")
    for name in set(columns) - {"source_result_index", "source_item_index", "period_end"}:
        facts[name] = facts[name].astype("string")
    return _identity({"facts": facts, "audit": pd.DataFrame(audits)}, record, request,
                     HTTP_PROVIDER, HTTP_NORMALIZER)


def _provenance(record, request):
    return {"normalizer_source_sha256": _source_sha(), "helper_source_sha256": _helpers(),
            "policy": json.loads(_json(POLICY)), "policy_sha256": _sha(POLICY),
            "source_provider": record["provider"], "source_request": request,
            "source_observed_at": record["observed_at"],
            "input_snapshots": [{name: record[name] for name in ("id", "raw_sha256", "observed_at")}],
            "issuer_identity_status": "unknown", "statement_scope": "unknown", "amount_unit_status": "unknown",
            "statement_completeness": "not_certified", "eligibility": POLICY["eligibility"]}


def _publish(store, record, normalizer, tables, provenance):
    existing = store.dataset(record["id"], normalizer)
    if existing is not None:
        if (existing.get("provenance") != provenance or set(existing.get("tables", {})) != set(tables)
                or any(existing["tables"][name]["rows"] != len(frame) for name, frame in tables.items())):
            raise ValueError("Existing source/policy/dependencies or table set changed")
        reader = OfflineDataReader(store.root)
        for name, frame in tables.items():
            actual = reader.read(snapshot_id=record["id"], normalizer=normalizer, table=name).frame
            if not actual.equals(frame.reset_index(drop=True)):
                raise ValueError("Existing table differs from its exact source cells")
        return existing
    return store.publish_tables(record, normalizer, tables, provenance=provenance)


def replay_statement_http(store, record):
    """Replay exact bytes; never select latest, fetch, infer periods or fill cells."""
    registered, request, body = _registered(store, record, HTTP_PROVIDER)
    _validate_http_request(request)
    tables = _http_tables(body, request, registered)
    provenance = {**_provenance(registered, request), "response_layer": "original_http_bytes",
                  "source_symbol_verified": bool(tables["audit"].source_symbol_verified.all()),
                  "fact_rows": len(tables["facts"]), "audit_rows": len(tables["audit"]),
                  "numeric_fact_rows": int(tables["facts"].value_status.eq("reported_numeric").sum())}
    return _publish(store, registered, HTTP_NORMALIZER, tables, provenance)


def capture_statement_http(store, *, symbol, statement, frequency, body, observed_at, contract_sha256=None):
    """Capture an already received successful HTTP body with explicit frequency."""
    if not isinstance(body, bytes):
        raise TypeError("Require original HTTP response bytes")
    request = _http_request(symbol, statement, frequency, contract_sha256)
    _http_tables(body, request, {"id": "0" * 32, "observed_at": utc_time(observed_at).isoformat()})
    record = store.capture(HTTP_PROVIDER, request, body, observed_at=observed_at)
    return {"record": record, "manifest": replay_statement_http(store, record)}


def _http_pin(store, record, request, started, finished, expected_manifest):
    registered, source_request, body = _registered(store, record, HTTP_PROVIDER)
    _validate_http_request(source_request)
    if (any(source_request[name] != request[name] for name in ("symbol", "statement", "frequency", "contract_sha256"))
            or source_request["adapter_version"] != request["yfinance_version"]
            or not started <= utc_time(registered["observed_at"]) <= finished):
        raise ValueError("HTTP dependency differs from library request/time")
    tables = _http_tables(body, source_request, registered)
    if expected_manifest is not None:
        if store.dataset(registered["id"], HTTP_NORMALIZER) != expected_manifest:
            raise ValueError("HTTP dependency materialization pin changed")
        OfflineDataReader(store.root).catalog(provider=HTTP_PROVIDER, request=source_request)
        # Recompute source-derived rows as well as verifying stored hashes.
        expected = {**_provenance(registered, source_request), "response_layer": "original_http_bytes",
                    "source_symbol_verified": bool(tables["audit"].source_symbol_verified.all()),
                    "fact_rows": len(tables["facts"]), "audit_rows": len(tables["audit"]),
                    "numeric_fact_rows": int(tables["facts"].value_status.eq("reported_numeric").sum())}
        _publish(store, registered, HTTP_NORMALIZER, tables, expected)
    return {name: registered[name] for name in ("id", "raw_sha256", "observed_at")}, bool(
        tables["audit"].source_symbol_verified.all())


def _frame_tables(content, record, request, verified):
    frame, rows = content["dataframe"], []
    periods = []
    for encoded in frame["columns"]["labels"]:
        label = frame_v1.decode_scalar(encoded)
        if ((isinstance(label, pd.Timestamp) and not pd.isna(label)) or
                (isinstance(label, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", label))):
            periods.append(frame_v1._period(encoded, record["observed_at"]))
        else:
            periods.append((pd.NaT, None))
    for row_position, values in enumerate(frame["data"]):
        metric = frame["index"]["labels"][row_position]
        for column_position, value in enumerate(values):
            label = frame["columns"]["labels"][column_position]
            period, timezone = periods[column_position]
            rows.append({"source_row_position": row_position, "source_column_position": column_position,
                         "metric_kind": metric["kind"], "metric_label": metric["value"],
                         "source_period_kind": label["kind"], "source_period_label": label["value"],
                         "original_period_timezone": timezone, "period_end": period,
                         "period_end_status": "unknown" if pd.isna(period) else "source_calendar_label",
                         "source_dtype": frame["dtypes"][column_position], "value_kind": value["kind"],
                         "value": value["value"], "value_status": frame_v1._value_status(value)})
    facts = pd.DataFrame(rows, columns=["source_row_position", "source_column_position", "metric_kind", "metric_label",
                                      "source_period_kind", "source_period_label", "original_period_timezone",
                                      "period_end", "period_end_status", "source_dtype", "value_kind", "value", "value_status"])
    for name in ("source_row_position", "source_column_position"):
        facts[name] = facts[name].astype("int64")
    facts["period_end"] = pd.to_datetime(facts.period_end, utc=True)
    facts["period_start"] = pd.Series(pd.NaT, index=facts.index, dtype="datetime64[ns, UTC]")
    for name in facts.columns:
        if facts[name].dtype == "object":
            facts[name] = facts[name].astype("string")
    counts = {name: int(facts.value_status.eq(name).sum()) for name in
              ("finite_numeric", "missing", "nonfinite", "nonnumeric")}
    audit = pd.DataFrame([{"source_matrix_rows": frame["shape"][0], "source_matrix_columns": frame["shape"][1],
                           "source_cells": len(facts), **{name + "_cells": value for name, value in counts.items()},
                           "typed_dataframe_json": _json(frame),
                           "status": "candidate_cells_present" if counts["finite_numeric"] else "unavailable"}])
    tables = _identity({"facts": facts, "audit": audit}, record, request, FRAME_PROVIDER, FRAME_NORMALIZER)
    for table in tables.values():
        for name, value in {"source_function": request["function"], "currency_status": "unknown",
                            "response_layer": "library_dataframe", "source_period_type_status": "unknown"}.items():
            table[name] = pd.Series(value, index=table.index, dtype="string")
        table["currency"] = pd.Series(pd.NA, index=table.index, dtype="string")
        table["source_symbol_verified"] = pd.Series(verified, index=table.index, dtype="bool")
    return tables


def capture_statement_frame(store, frame, *, symbol, method, frequency, yfinance_version, started_at, finished_at,
                            http_records=(), contract_sha256=None):
    """Capture an already returned frame; independently pin same-call raw inputs."""
    request = _frame_request(symbol, method, frequency, yfinance_version, contract_sha256)
    started, finished = utc_time(started_at), utc_time(finished_at)
    if finished < started:
        raise ValueError("Library call finish precedes start")
    if not isinstance(http_records, (list, tuple)):
        raise TypeError("Require an explicit HTTP record list")
    inputs, seen = [], set()
    for source in http_records:
        manifest = store.dataset(source["id"], HTTP_NORMALIZER)
        pin, _ = _http_pin(store, source, request, started, finished, manifest)
        if pin["id"] in seen:
            raise ValueError("Duplicate HTTP dependency")
        seen.add(pin["id"])
        inputs.append({**pin, "manifest": manifest})
    content = {"schema": FRAME_SCHEMA, "request": request, "response_layer": "library_dataframe",
               "normalizer_source_sha256": _source_sha(), "helper_source_sha256": _helpers(),
               "policy_sha256": _sha(POLICY), "library_call_started_at": started.isoformat(),
               "library_call_finished_at": finished.isoformat(), "http_inputs": inputs,
               "dataframe": frame_v1.encode_dataframe(frame)}
    frame_v1._validate_frame(content["dataframe"])
    _frame_tables(content, {"id": "0" * 32, "observed_at": finished.isoformat()}, request, False)
    record = store.capture(FRAME_PROVIDER, request, _json(content).encode(), observed_at=finished)
    return {"record": record, "manifest": replay_statement_frame(store, record)}


def replay_statement_frame(store, record):
    """Recreate typed candidates from one pinned frame without HTTP or SDK use."""
    registered, request, body = _registered(store, record, FRAME_PROVIDER)
    if not isinstance(request, dict) or request != _frame_request(
        request.get("symbol"), request.get("function"), request.get("frequency"),
        request.get("yfinance_version"), request.get("contract_sha256")
    ):
        raise ValueError("Frame request schema/frequency/source code differs")
    content = frame_v1._strict_json(body)
    fields = {"schema", "request", "response_layer", "normalizer_source_sha256", "helper_source_sha256",
              "policy_sha256", "library_call_started_at", "library_call_finished_at", "http_inputs", "dataframe"}
    if (not isinstance(content, dict) or set(content) != fields or content["schema"] != FRAME_SCHEMA
            or content["request"] != request or content["response_layer"] != "library_dataframe"
            or content["normalizer_source_sha256"] != _source_sha() or content["helper_source_sha256"] != _helpers()
            or content["policy_sha256"] != _sha(POLICY)):
        raise ValueError("Frame payload schema/identity/source code/policy differs")
    started, finished = utc_time(content["library_call_started_at"]), utc_time(content["library_call_finished_at"])
    if finished < started or finished.isoformat() != registered["observed_at"]:
        raise ValueError("Frame call timestamps differ from observation")
    frame_v1._validate_frame(content["dataframe"])
    if not isinstance(content["http_inputs"], list):
        raise TypeError("Require an explicit HTTP input list")
    provenance = _provenance(registered, request)
    proofs, manifests, seen = [], [], {registered["id"]}
    for supplied in content["http_inputs"]:
        if not isinstance(supplied, dict) or set(supplied) != {"id", "raw_sha256", "observed_at", "manifest"}:
            raise ValueError("Incomplete HTTP dependency pin")
        dependency = store.get(supplied["id"])
        if dependency is None or any(supplied[name] != dependency[name] for name in ("raw_sha256", "observed_at")):
            raise ValueError("HTTP dependency differs from exact catalog pin")
        if supplied["id"] in seen:
            raise ValueError("Duplicate HTTP dependency")
        seen.add(supplied["id"])
        pin, proof = _http_pin(store, dependency, request, started, finished, supplied["manifest"])
        provenance["input_snapshots"].append(pin)
        proofs.append(proof)
        if supplied["manifest"] is not None:
            manifests.append(supplied["manifest"])
    verified = bool(proofs) and all(proofs)
    tables = _frame_tables(content, registered, request, verified)
    provenance.update({"input_manifests": manifests, "response_layer": "library_dataframe",
                       "yfinance_version": request["yfinance_version"], "source_symbol_verified": verified,
                       "library_call_started_at": started.isoformat(), "library_call_finished_at": finished.isoformat(),
                       "http_raw_capture_status": "captured_dependencies" if proofs else "not_captured",
                       "http_statement_binding_basis": POLICY["statement_binding"],
                       "currency_status": "unknown", "dataframe_sha256": _sha(content["dataframe"]),
                       "matrix_shape": content["dataframe"]["shape"]})
    return _publish(store, registered, FRAME_NORMALIZER, tables, provenance)
