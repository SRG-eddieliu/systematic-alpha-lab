"""Typed snapshots of library-returned financial DataFrames, never HTTP claims.

This candidate-only adapter has no collector, credentials or yfinance import.
It preserves values present at capture time; precision lost before the library
returned its DataFrame cannot be recovered. Use a separate closed private root.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .offline_reader import OfflineDataReader
from .snapshot_store import SnapshotStore, utc_time

PROVIDER = "yahoo_yfinance_dataframe"
NORMALIZER = "yf_statement_cells_v1"
SCHEMA = "yf_statement_dataframe_capture_v1"
FRAME_SCHEMA = "yf_typed_dataframe_v1"
HTTP_PROVIDER = "yahoo_financial_timeseries"
HTTP_NORMALIZER = "yf_timeseries_cells_v1"
METHODS = {"get_income_stmt": "income", "get_balance_sheet": "balance-sheet", "get_cash_flow": "cash-flow"}
POLICY = {
    "response_layer": "library_dataframe", "frequency": "yearly",
    "scalar_encoding": "typed_strings_including_float_hex_not_original_http_precision",
    "axes": "ordered_single_level_duplicate_labels_preserved",
    "period_basis": "source_calendar_label_represented_at_UTC_midnight_not_an_availability_instant",
    "metadata": "currency_units_scope_company_identity_unknown_without_independent_evidence",
    "eligibility": "candidate_only_not_certified",
}
_RECORD_FIELDS = ("id", "request_id", "provider", "request_json", "observed_at", "raw_sha256", "raw_path")
_MISSING = {"none", "pandas_na", "nat"}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _source_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _strict_json(body):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("Duplicate snapshot JSON field")
            result[name] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite JSON scalar must use the typed codec")

    return json.loads(body, object_pairs_hook=unique, parse_constant=invalid)


def encode_scalar(value):
    """Encode supported source scalars without numeric inference or rounding."""
    if value is None:
        return {"kind": "none", "value": ""}
    if value is pd.NA:
        return {"kind": "pandas_na", "value": ""}
    if value is pd.NaT:
        return {"kind": "nat", "value": ""}
    if isinstance(value, pd.Timestamp):
        result = {"kind": "timestamp", "value": _json({
            "iso": value.isoformat(), "timezone": None if value.tz is None else str(value.tz)})}
        decode_scalar(result)
        return result
    if isinstance(value, (bool, np.bool_)):
        return {"kind": "np_bool" if isinstance(value, np.bool_) else "bool", "value": "true" if value else "false"}
    if isinstance(value, (int, np.integer)):
        return {"kind": "np_" + value.dtype.name if isinstance(value, np.integer) else "int", "value": str(int(value))}
    if isinstance(value, (float, np.floating)):
        if isinstance(value, np.floating) and value.dtype.itemsize > 8:
            raise TypeError("Floating types wider than 64 bits are unsupported")
        number = float(value)
        text = "nan" if math.isnan(number) else "inf" if number == math.inf else "-inf" if number == -math.inf else number.hex()
        return {"kind": "np_" + value.dtype.name if isinstance(value, np.floating) else "float", "value": text}
    if isinstance(value, str):
        return {"kind": "string", "value": value}
    raise TypeError("Unsupported source scalar type; do not stringify it implicitly")


def decode_scalar(encoded):
    """Decode a canonical scalar; reject extra fields and lossy coercions."""
    if (not isinstance(encoded, dict) or set(encoded) != {"kind", "value"}
            or not isinstance(encoded["kind"], str) or not isinstance(encoded["value"], str)):
        raise ValueError("Invalid typed scalar")
    kind, value = encoded["kind"], encoded["value"]
    if kind in _MISSING:
        if value:
            raise ValueError("Missing scalar must retain its canonical empty marker")
        return {"none": None, "pandas_na": pd.NA, "nat": pd.NaT}[kind]
    if kind == "string":
        return value
    if kind in {"bool", "np_bool"} and value in {"true", "false"}:
        return np.bool_(value == "true") if kind == "np_bool" else value == "true"
    if kind == "int" or re.fullmatch(r"np_u?int(?:8|16|32|64)", kind):
        if not re.fullmatch(r"0|-?[1-9][0-9]*", value):
            raise ValueError("Invalid integer scalar")
        result = int(value)
        if kind != "int":
            dtype = np.dtype(kind[3:])
            limits = np.iinfo(dtype)
            if not limits.min <= result <= limits.max:
                raise ValueError("Integer scalar exceeds its declared type")
            result = dtype.type(result)
        return result
    if kind in {"float", "np_float16", "np_float32", "np_float64"}:
        try:
            number = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}.get(value)
            number = float.fromhex(value) if number is None else number
        except ValueError:
            raise ValueError("Invalid hexadecimal float scalar") from None
        result = np.dtype(kind[3:]).type(number) if kind != "float" else number
        if encode_scalar(result) != encoded:
            raise ValueError("Float scalar does not preserve its declared type/value")
        return result
    if kind == "timestamp":
        info = _strict_json(value)
        if (not isinstance(info, dict) or set(info) != {"iso", "timezone"} or not isinstance(info["iso"], str)
                or info["timezone"] is not None and not isinstance(info["timezone"], str)):
            raise ValueError("Invalid timestamp scalar")
        try:
            stamp = pd.Timestamp(info["iso"])
            if pd.isna(stamp) or (stamp.tz is None) != (info["timezone"] is None):
                raise ValueError("Timestamp timezone differs from its source marker")
            if info["timezone"] is not None:
                stamp = stamp.tz_convert(info["timezone"])
            canonical = _json({"iso": stamp.isoformat(), "timezone": None if stamp.tz is None else str(stamp.tz)})
            if canonical != value:
                raise ValueError("Timestamp scalar is not canonical")
            return stamp
        except (TypeError, ValueError, KeyError):
            raise ValueError("Unsupported timestamp/timezone scalar") from None
    raise ValueError("Unsupported typed scalar kind/value")


def encode_dataframe(frame):
    """Encode axes/cells by position; never use label-keyed dicts or to_json."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Require a DataFrame returned by the library")
    if any(isinstance(axis, (pd.MultiIndex, pd.CategoricalIndex)) for axis in (frame.index, frame.columns)):
        raise ValueError("MultiIndex/categorical financial axes are unsupported in this version")
    if any(isinstance(dtype, (pd.CategoricalDtype, pd.SparseDtype)) for dtype in frame.dtypes):
        raise TypeError("Categorical/sparse dtype metadata is unsupported")
    return {
        "schema": FRAME_SCHEMA, "shape": [int(frame.shape[0]), int(frame.shape[1])],
        "index": {"dtype": str(frame.index.dtype), "name": encode_scalar(frame.index.name),
                  "labels": [encode_scalar(value) for value in frame.index]},
        "columns": {"dtype": str(frame.columns.dtype), "name": encode_scalar(frame.columns.name),
                    "labels": [encode_scalar(value) for value in frame.columns]},
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "data": [[encode_scalar(frame.iat[row, column]) for column in range(frame.shape[1])]
                 for row in range(frame.shape[0])],
    }


def _validate_frame(frame):
    if not isinstance(frame, dict) or set(frame) != {"schema", "shape", "index", "columns", "dtypes", "data"}:
        raise ValueError("Invalid encoded frame fields")
    if frame["schema"] != FRAME_SCHEMA or not isinstance(frame["shape"], list) or len(frame["shape"]) != 2 or any(
        isinstance(size, bool) or not isinstance(size, int) or size < 0 for size in frame["shape"]
    ):
        raise ValueError("Invalid encoded frame version/shape")
    rows, columns = frame["shape"]
    for name, size in (("index", rows), ("columns", columns)):
        axis = frame[name]
        if (not isinstance(axis, dict) or set(axis) != {"dtype", "name", "labels"}
                or not isinstance(axis["dtype"], str) or not axis["dtype"]
                or not isinstance(axis["labels"], list) or len(axis["labels"]) != size):
            raise ValueError("Encoded axis differs from its declared shape")
        decode_scalar(axis["name"])
        for label in axis["labels"]:
            decode_scalar(label)
    if (not isinstance(frame["dtypes"], list) or len(frame["dtypes"]) != columns
            or any(not isinstance(dtype, str) or not dtype for dtype in frame["dtypes"])
            or not isinstance(frame["data"], list) or len(frame["data"]) != rows):
        raise ValueError("Encoded cell/dtype dimensions differ from the frame")
    for row in frame["data"]:
        if not isinstance(row, list) or len(row) != columns:
            raise ValueError("Encoded cell dimensions differ from the frame")
        for value in row:
            decode_scalar(value)


def _request(symbol, method, version, contract):
    if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol)
            or not isinstance(method, str) or method not in METHODS):
        raise ValueError("Declare an explicit supported symbol and annual statement method")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}", version):
        raise ValueError("Declare the actual library version used by the caller")
    if contract is not None and (not isinstance(contract, str) or not re.fullmatch(r"[0-9a-f]{64}", contract)):
        raise ValueError("Invalid optional research contract fingerprint")
    return {"symbol": symbol, "function": method, "frequency": "yearly", "as_dict": False, "pretty": False,
            "yfinance_version": version, "contract_sha256": contract}


def _registered(store, record, provider):
    registered = store.get(record["id"])
    if registered is None or any(record.get(name) != registered[name] for name in _RECORD_FIELDS):
        raise ValueError("Source record differs from its exact catalog pin")
    request = _strict_json(registered["request_json"])
    if registered["provider"] != provider or registered["request_id"] != SnapshotStore.request_id(provider, request):
        raise ValueError("Source provider/request differs from its catalog identity")
    relative = Path(registered["raw_path"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in registered["raw_path"]:
        raise ValueError("Source path escapes the data root")
    path = (store.root / relative).resolve(strict=True)
    if not path.is_relative_to(store.root) or not path.is_file():
        raise ValueError("Source path escapes the data root")
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != registered["raw_sha256"]:
        raise ValueError("Raw source fingerprint differs")
    return registered, request, _strict_json(body)


def _http_pin(store, record, request, started, finished, expected_manifest=None):
    registered, source_request, body = _registered(store, record, HTTP_PROVIDER)
    if (source_request.get("symbol") != request["symbol"]
            or source_request.get("statement") != METHODS[request["function"]]
            or source_request.get("frequency") != "annual"
            or not started <= utc_time(registered["observed_at"]) <= finished):
        raise ValueError("HTTP dependency differs from the explicit library request/time")
    if (source_request.get("contract_sha256") is not None and request["contract_sha256"] is not None
            and source_request["contract_sha256"] != request["contract_sha256"]):
        raise ValueError("HTTP dependency differs from the explicit contract")
    timeseries = body.get("timeseries") if isinstance(body, dict) else None
    results = timeseries.get("result") if isinstance(timeseries, dict) else None
    if (not isinstance(timeseries, dict) or timeseries.get("error") is not None
            or results is not None and not isinstance(results, list)):
        raise ValueError("HTTP dependency is not a successful financial-timeseries response")
    verified = isinstance(results, list) and bool(results)
    for result in results if isinstance(results, list) else []:
        meta = result.get("meta") if isinstance(result, dict) else None
        symbols = meta.get("symbol") if isinstance(meta, dict) else None
        if symbols is None:
            verified = False
        elif symbols not in (request["symbol"], [request["symbol"]]):
            raise ValueError("HTTP source symbol conflicts with the requested symbol")
    if expected_manifest is not None:
        reader = OfflineDataReader(store.root)
        # The original reader verifies path containment and complete raw/table
        # dependencies before SnapshotStore reads the existing table manifest.
        reader.catalog(provider=HTTP_PROVIDER, request=source_request)
        if store.dataset(registered["id"], HTTP_NORMALIZER) != expected_manifest:
            raise ValueError("Pinned HTTP materialization differs from its catalog")
    pin = {name: registered[name] for name in ("id", "raw_sha256", "observed_at")}
    return pin, verified


def capture_yfinance_statement(store, frame, *, symbol, method, yfinance_version, started_at, finished_at,
                               http_records=(), contract_sha256=None):
    """Capture an already returned frame; never call a company endpoint."""
    request = _request(symbol, method, yfinance_version, contract_sha256)
    started, finished = utc_time(started_at), utc_time(finished_at)
    if finished < started:
        raise ValueError("Library return time precedes its call start")
    if not isinstance(http_records, (list, tuple)):
        raise TypeError("HTTP dependencies require an explicit record list")
    dependencies, seen = [], set()
    for record in http_records:
        pin, _ = _http_pin(store, record, request, started, finished)
        if pin["id"] in seen:
            raise ValueError("Duplicate HTTP dependency")
        seen.add(pin["id"])
        OfflineDataReader(store.root).catalog(provider=HTTP_PROVIDER, request=_strict_json(record["request_json"]))
        manifest = store.dataset(pin["id"], HTTP_NORMALIZER)
        dependencies.append({**pin, "manifest": manifest})
    content = {"schema": SCHEMA, "request": request, "response_layer": "library_dataframe",
               "library_call_started_at": started.isoformat(), "library_call_finished_at": finished.isoformat(),
               "encoder_source_sha256": _source_sha(), "policy_sha256": _sha(POLICY),
               "http_inputs": dependencies, "dataframe": encode_dataframe(frame)}
    record = store.capture(PROVIDER, request, _json(content).encode(), observed_at=finished)
    return {"record": record, "manifest": replay_yfinance_statement(store, record)}


def _period(encoded, observed):
    label = decode_scalar(encoded)
    if isinstance(label, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", label):
        label = pd.Timestamp(label)
    if not isinstance(label, pd.Timestamp) or pd.isna(label):
        raise ValueError("Annual statement columns require explicit source date labels")
    # Source labels retain their own local calendar date and original timezone.
    # UTC midnight is only the reader's representation of that calendar label.
    period = pd.Timestamp(label.date(), tz="UTC")
    if period > pd.Timestamp(observed).normalize():
        raise ValueError("Source financial period exceeds the library observation date")
    return period, None if label.tz is None else str(label.tz)


def _value_status(encoded):
    if encoded["kind"] in _MISSING or encoded["value"] == "nan" and (
        encoded["kind"] == "float" or encoded["kind"].startswith("np_float")
    ):
        return "missing"
    if encoded["kind"] == "int" or re.fullmatch(r"np_u?int(?:8|16|32|64)", encoded["kind"]):
        return "finite_numeric"
    if encoded["kind"] == "float" or encoded["kind"].startswith("np_float"):
        return "nonfinite" if encoded["value"] in {"inf", "-inf"} else "finite_numeric"
    return "nonnumeric"


def _tables(content, record, request, verified):
    frame, rows = content["dataframe"], []
    periods = [_period(label, record["observed_at"]) for label in frame["columns"]["labels"]]
    for row_number, values in enumerate(frame["data"]):
        metric = frame["index"]["labels"][row_number]
        for column_number, value in enumerate(values):
            period, timezone = periods[column_number]
            label = frame["columns"]["labels"][column_number]
            rows.append({"source_row_position": row_number, "source_column_position": column_number,
                         "metric_kind": metric["kind"], "metric_label": metric["value"],
                         "source_period_kind": label["kind"], "source_period_label": label["value"],
                         "original_period_timezone": timezone, "period_end": period,
                         "source_dtype": frame["dtypes"][column_number],
                         "value_kind": value["kind"], "value": value["value"], "value_status": _value_status(value)})
    facts = pd.DataFrame(rows, columns=[
        "source_row_position", "source_column_position", "metric_kind", "metric_label", "source_period_kind",
        "source_period_label", "original_period_timezone", "period_end", "source_dtype", "value_kind", "value",
        "value_status",
    ])
    facts["period_end"] = pd.to_datetime(facts.period_end, utc=True)
    for name in ("source_row_position", "source_column_position"):
        facts[name] = facts[name].astype("int64")
    finite = int(facts.value_status.eq("finite_numeric").sum())
    audit = pd.DataFrame([{"source_matrix_rows": frame["shape"][0], "source_matrix_columns": frame["shape"][1],
                           "source_cells": len(facts), "finite_numeric_cells": finite,
                           "missing_cells": int(facts.value_status.eq("missing").sum()),
                           "nonfinite_cells": int(facts.value_status.eq("nonfinite").sum()),
                           "nonnumeric_cells": int(facts.value_status.eq("nonnumeric").sum()),
                           "status": "candidate_cells_present" if finite else "unavailable"}])
    for table in (facts, audit):
        for name, value in {"provider": PROVIDER, "symbol": request["symbol"], "source_function": request["function"],
                            "normalizer": NORMALIZER, "snapshot_id": record["id"], "period_type": "annual_requested",
                            "period_basis": POLICY["period_basis"], "availability_basis": "not_supplied",
                            "identifier_basis": "requested_symbol_issuer_unverified", "amount_unit_status": "unknown",
                            "currency_status": "unknown", "statement_scope": "unknown", "flow_basis": "unknown",
                            "eligibility": "candidate_only_not_certified", "response_layer": "library_dataframe"}.items():
            table[name] = pd.Series(value, index=table.index, dtype="string")
        table["observed_at"] = pd.Series(pd.Timestamp(record["observed_at"]), index=table.index,
                                          dtype="datetime64[ns, UTC]")
        table["available_at"] = pd.Series(pd.NaT, index=table.index, dtype="datetime64[ns, UTC]")
        table["asset_id"] = pd.Series(pd.NA, index=table.index, dtype="string")
        table["currency"] = pd.Series(pd.NA, index=table.index, dtype="string")
        table["source_symbol_verified"] = pd.Series(verified, index=table.index, dtype="bool")
    for name in facts.columns:
        if facts[name].dtype == "object":
            facts[name] = facts[name].astype("string")
    return {"facts": facts, "audit": audit}


def replay_yfinance_statement(store, record):
    """Validate exact typed library evidence and materialize candidate tables."""
    registered, request, content = _registered(store, record, PROVIDER)
    if not isinstance(request, dict) or request != _request(
        request.get("symbol"), request.get("function"), request.get("yfinance_version"), request.get("contract_sha256")
    ):
        raise ValueError("Unexpected library method/frequency/version/request")
    fields = {"schema", "request", "response_layer", "library_call_started_at", "library_call_finished_at",
              "encoder_source_sha256", "policy_sha256", "http_inputs", "dataframe"}
    if (not isinstance(content, dict) or set(content) != fields or content["schema"] != SCHEMA
            or content["request"] != request or content["response_layer"] != "library_dataframe"
            or content["encoder_source_sha256"] != _source_sha() or content["policy_sha256"] != _sha(POLICY)):
        raise ValueError("Library capture identity/schema/source code/policy changed")
    started, finished = utc_time(content["library_call_started_at"]), utc_time(content["library_call_finished_at"])
    if finished < started or finished.isoformat() != registered["observed_at"]:
        raise ValueError("Library call timestamps differ from the source observation")
    _validate_frame(content["dataframe"])
    inputs = [{name: registered[name] for name in ("id", "raw_sha256", "observed_at")}]
    manifests, proofs, seen = [], [], {registered["id"]}
    if not isinstance(content["http_inputs"], list):
        raise ValueError("Invalid HTTP dependency list")
    for supplied in content["http_inputs"]:
        if not isinstance(supplied, dict) or set(supplied) != {"id", "raw_sha256", "observed_at", "manifest"}:
            raise ValueError("Incomplete HTTP dependency pin")
        dependency = store.get(supplied["id"])
        if dependency is None or any(supplied[name] != dependency[name] for name in ("raw_sha256", "observed_at")):
            raise ValueError("HTTP dependency raw pin differs from its catalog")
        if supplied["id"] in seen:
            raise ValueError("Duplicate HTTP dependency")
        seen.add(supplied["id"])
        pin, proof = _http_pin(store, dependency, request, started, finished, supplied["manifest"])
        inputs.append(pin)
        proofs.append(proof)
        if supplied["manifest"] is not None:
            manifests.append(supplied["manifest"])
    verified = bool(proofs) and all(proofs)
    tables = _tables(content, registered, request, verified)
    provenance = {
        "normalizer_source_sha256": _source_sha(), "encoder_source_sha256": content["encoder_source_sha256"],
        "policy": _strict_json(_json(POLICY)), "policy_sha256": _sha(POLICY),
        "source_request": request, "source_provider": PROVIDER,
        "source_observed_at": registered["observed_at"], "input_snapshots": inputs, "input_manifests": manifests,
        "response_layer": "library_dataframe", "yfinance_version": request["yfinance_version"],
        "library_call_started_at": content["library_call_started_at"],
        "library_call_finished_at": content["library_call_finished_at"],
        "http_raw_capture_status": "captured_dependencies" if proofs else "not_captured",
        "http_statement_binding_basis": "collector_context_only_not_independent_source_semantics",
        "source_symbol_verified": verified,
        "symbol_verification_basis": "all_http_timeseries_meta_symbols" if verified else "not_verified",
        "issuer_identity_status": "unknown", "currency_status": "unknown", "amount_unit_status": "unknown",
        "statement_scope": "unknown", "eligibility": "candidate_only_not_certified",
        "dataframe_sha256": _sha(content["dataframe"]), "matrix_shape": content["dataframe"]["shape"],
    }
    # Validate an existing version fully before allowing SnapshotStore's early
    # return. A changed encoder, policy or dependency needs a new version.
    existing = store.dataset(registered["id"], NORMALIZER)
    if existing is not None:
        if (existing["provenance"] != provenance or set(existing["tables"]) != set(tables)
                or any(existing["tables"][name]["rows"] != len(frame) for name, frame in tables.items())):
            raise ValueError("Existing library materialization source/policy/dependencies changed")
        reader = OfflineDataReader(store.root)
        for name, frame in tables.items():
            result = reader.read(snapshot_id=registered["id"], normalizer=NORMALIZER, table=name)
            if not result.frame.equals(frame.reset_index(drop=True)):
                raise ValueError("Existing library table differs from its exact typed source cells")
        return existing
    return store.publish_tables(registered, NORMALIZER, tables, provenance=provenance)
