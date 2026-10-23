"""Pure offline presence audit of the bounded, unaccepted supplement pilot.

No source is selected, filled, compared arithmetically or accepted. Contract
calendar dates are target selectors, never evidence of an observation's start,
annual duration, issuer, units, accounting scope or coherent filing version.
Excluded-row counts use native AV report rows and Yahoo metric/period rows;
they are not counts of distinct fiscal periods or cells in the 354 denominator.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import numpy as np
import pandas as pd

AUDIT_VERSION = "supplement_candidate_presence_v1"
AV = "alpha_vantage"
YAHOO = "yahoo_financial_timeseries"
_YAHOO_FIELDS = {"yahoo_income_fields": "income", "yahoo_balance_sheet_fields": "balance-sheet",
                 "yahoo_cash_flow_fields": "cash-flow"}
_AV_STATEMENTS = {"INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW"}
_MISSING_LITERALS = {"", "none", "null", "nan", "n/a"}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _original(value):
    """JSON-safe evidence without promoting source integers to floats."""
    if value is None:
        return {"kind": "none", "value": None}
    if value is pd.NA:
        return {"kind": "pandas_na", "value": None}
    if value is pd.NaT:
        return {"kind": "nat", "value": None}
    if isinstance(value, (bool, np.bool_)):
        return {"kind": "boolean", "value": bool(value)}
    if isinstance(value, (int, np.integer)):
        return {"kind": "integer", "value": int(value)}
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return {"kind": "float", "value": number if math.isfinite(number) else str(number),
                "hex": number.hex()}
    if isinstance(value, Decimal):
        return {"kind": "decimal", "value": str(value)}
    if isinstance(value, str):
        return {"kind": "string", "value": value}
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return {"kind": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, (list, dict)):
        return {"kind": type(value).__name__, "value": json.loads(_json(value))}
    raise TypeError("Unsupported source scalar in candidate evidence")


def _presence(value, *, absent=False):
    if absent:
        return "field_absent"
    if value is None:
        return "source_null"
    if value is pd.NA or value is pd.NaT:
        return "pandas_missing"
    if isinstance(value, (bool, np.bool_)):
        return "boolean"
    if isinstance(value, str) and value.strip().lower() in _MISSING_LITERALS:
        return "missing_literal"
    if not isinstance(value, (str, int, float, np.integer, np.floating, Decimal)):
        return "invalid_numeric"
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return "invalid_numeric"
    if not number.is_finite():
        return "nonfinite"
    return "explicit_zero" if number == 0 else "finite_candidate"


def _cell(frame, row, name, default=None):
    positions = [index for index, column in enumerate(frame.columns) if column == name]
    if len(positions) > 1:
        raise ValueError("Ambiguous source metadata column")
    return frame.iat[row, positions[0]] if positions else default


def _end(value):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return None
    if isinstance(value, (pd.Timestamp, datetime, date)) and value is not pd.NaT:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp) or any((stamp.hour, stamp.minute, stamp.second, stamp.microsecond, stamp.nanosecond)):
            return None
        return stamp.date().isoformat()
    return None


def _plan(contract):
    _json(contract)
    if contract.get("contract_id") != "av_primary_supplement_pilot_v1":
        raise ValueError("Require the explicit versioned pilot contract")
    issuers, concepts = contract["scope"]["issuers"], contract["candidate_concepts"]
    if len(issuers) != 3 or len(concepts) != 5:
        raise ValueError("This audit retains the frozen three-issuer/five-concept denominator")
    native, seen = [], set()
    for concept, definition in concepts.items():
        declarations = [(AV, statement, fields) for statement, fields in definition.get("av_fields", {}).items()]
        declarations += [(YAHOO, statement, definition.get(name, [])) for name, statement in _YAHOO_FIELDS.items()]
        for provider, statement, fields in declarations:
            if (provider == AV and statement not in _AV_STATEMENTS or not isinstance(fields, list)
                    or any(not isinstance(field, str) or not field for field in fields)):
                raise ValueError("Invalid native candidate field declaration")
            for field in fields:
                identity = provider, statement, field
                if identity in seen:
                    raise ValueError("Duplicate native field would change the fixed denominator")
                seen.add(identity)
                native.append({"concept": concept, "native_source": provider, "statement": statement, "field": field})
    if len(native) != 59:
        raise ValueError("The frozen contract requires exactly 59 native candidate fields")
    targets, symbols, yahoo_symbols, ciks = [], set(), set(), set()
    for issuer in issuers:
        if (len(issuer["periods"]) != 2 or issuer["av_symbol"] in symbols or issuer["cik"] in ciks
                or issuer["yahoo_symbol"] in yahoo_symbols):
            raise ValueError("The frozen contract requires six distinct issuer-period targets")
        symbols.add(issuer["av_symbol"])
        yahoo_symbols.add(issuer["yahoo_symbol"])
        ciks.add(issuer["cik"])
        if not isinstance(issuer["cik"], str) or not re.fullmatch(r"\d{10}", issuer["cik"]):
            raise ValueError("Declare the contract issuer CIK without symbol inference")
        ends, years = set(), set()
        for period in issuer["periods"]:
            start, end = _end(period["period_start"]), _end(period["period_end"])
            year = period["fiscal_year"]
            if (start is None or end is None or start > end or end in ends or isinstance(year, bool)
                    or not isinstance(year, int) or year in years):
                raise ValueError("Declare exact distinct target calendar periods")
            ends.add(end)
            years.add(year)
            targets.append({"symbol": issuer["av_symbol"], "yahoo_symbol": issuer["yahoo_symbol"],
                            "cik": issuer["cik"], "fiscal_year": period["fiscal_year"],
                            "target_start": start, "target_end": end})
    return native, targets


def _entries(av_statements, yahoo_statements, targets):
    allowed_av = {(target["symbol"], statement) for target in targets for statement in _AV_STATEMENTS}
    allowed_yahoo = {(target["yahoo_symbol"], statement) for target in targets for statement in _YAHOO_FIELDS.values()}
    if not isinstance(av_statements, dict) or not isinstance(yahoo_statements, dict):
        raise TypeError("Declare explicit source-statement dictionaries")
    if set(av_statements) - allowed_av or set(yahoo_statements) - allowed_yahoo:
        raise ValueError("Source dictionary is outside the selected issuer/statement scope")
    entries = {}
    for provider, sources in ((AV, av_statements), (YAHOO, yahoo_statements)):
        for (symbol, statement), supplied in sources.items():
            values = [supplied] if provider == AV else supplied
            if not isinstance(values, list):
                raise TypeError("Yahoo statements require an explicit list of captured chunks")
            prepared = []
            for item in values:
                if (not isinstance(item, dict) or not isinstance(item.get("frame"), pd.DataFrame)
                        or not isinstance(item.get("pin"), dict)):
                    raise TypeError("Each source needs a DataFrame and a JSON-safe pin dictionary")
                pin = json.loads(_json(item["pin"]))
                frame = item["frame"]
                _check_identity(frame, pin, provider, symbol, statement)
                if provider == YAHOO and not frame.empty and not {
                    "source_metric", "period_end", "source_value_json", "source_value_type", "value_status"
                }.issubset(frame.columns):
                    raise ValueError("Yahoo candidates require the original timeseries facts schema")
                periods = []
                for row in range(len(frame)):
                    label = _cell(frame, row, "fiscalDateEnding") if provider == AV and (
                        "fiscalDateEnding" in frame.columns) else _cell(frame, row, "period_end")
                    periods.append((label, _end(label)))
                prepared.append({"frame": frame, "pin": pin, "periods": periods})
            entries[provider, symbol, statement] = prepared
    return entries


def _check_identity(frame, pin, provider, symbol, statement):
    """Reject contradictory supplied labels; agreement is not verification."""
    def supplied(value):
        if value is None or value is pd.NA or value is pd.NaT:
            return False
        if isinstance(value, (float, np.floating)) and math.isnan(float(value)):
            return False
        return not isinstance(value, str) or bool(value.strip())

    def check(value, expected):
        if supplied(value) and (not isinstance(value, str) or value != expected):
            raise ValueError("Source identity conflicts with its explicit dictionary key")

    for column, expected in {"symbol": symbol, "provider": provider, "source_statement": statement,
                             "source_function": statement}.items():
        if column in frame.columns:
            for row in range(len(frame)):
                check(_cell(frame, row, column), expected)
    expected = {"provider": provider, "symbol": symbol, "statement": statement, "function": statement,
                "source_statement": statement, "source_function": statement}
    for name, value in expected.items():
        if name in pin:
            check(pin[name], value)
    request = pin.get("request")
    if request is not None:
        if not isinstance(request, dict):
            raise ValueError("Source pin request must be an explicit metadata dictionary")
        for name, value in expected.items():
            if name in request:
                check(request[name], value)


def _currency(frame, row, provider):
    name = "reportedCurrency" if provider == AV and "reportedCurrency" in frame.columns else "currency"
    value = _cell(frame, row, name)
    return {"source_column": name if name in frame.columns else None, "original": _original(value),
            "status": "reported_unverified" if isinstance(value, str) and re.fullmatch(r"[A-Z]{3}", value)
            else "unknown"}


def _frequency(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return "unknown"
    if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
        return "unknown"
    label = str(value).strip().upper()
    if label == "12M":
        return "annual_label_unverified_duration"
    if label in {"TTM", "TRAILING", "YTD", "Q", "QUARTERLY", "4Q"} or re.fullmatch(r"\d+M", label):
        return "annual_scope_mismatch"
    return "source_label_unreviewed"


def _candidate(entry, row, provider, field, column=None):
    frame = entry["frame"]
    base = {"pin": entry["pin"], "source_row_position": row,
            "source_period_original": _original(entry["periods"][row][0]),
            "currency_evidence": _currency(frame, row, provider),
            "source_period_start_original": _original(_cell(frame, row, "period_start")),
            "unit_scope_status": "units_scope_unverified", "version_status": "source_version_unreviewed"}
    if provider == AV:
        value = frame.iat[row, column] if column is not None else None
        return {**base, "source_column_position": column, "field": field,
                "original_value": _original(value) if column is not None else {"kind": "absent", "value": None},
                "presence_status": _presence(value, absent=column is None),
                "period_frequency_status": "annual_requested_not_certified"}
    lexeme, kind = _cell(frame, row, "source_value_json"), _cell(frame, row, "source_value_type")
    if kind is pd.NA or lexeme is pd.NA or kind == "absent":
        status = "field_absent"
    elif kind == "null":
        status = "source_null"
    elif kind == "boolean":
        status = "boolean"
    else:
        status = _presence(lexeme)
    source_period = _cell(frame, row, "source_period_type")
    return {**base, "source_metric": _original(_cell(frame, row, "source_metric")),
            "source_value_json": _original(lexeme), "source_value_type": _original(kind),
            "source_value_status": _original(_cell(frame, row, "value_status")),
            "source_period_type": _original(source_period), "presence_status": status,
            "period_frequency_status": _frequency(source_period)}


def _unmatched(entries, targets, native):
    rows = []
    for (provider, source_symbol, statement), captures in entries.items():
        selected = [target for target in targets if target["symbol" if provider == AV else "yahoo_symbol"] == source_symbol]
        exact_ends = {target["target_end"] for target in selected}
        fields = [item["field"] for item in native if item["native_source"] == provider and item["statement"] == statement]
        for capture_index, entry in enumerate(captures):
            frame = entry["frame"]
            for row, (label, end) in enumerate(entry["periods"]):
                if end in exact_ends:
                    continue
                if provider == AV:
                    source_metric = None
                    source_fields = [field for field in frame.columns if field in fields]
                else:
                    metric = _cell(frame, row, "source_metric")
                    source_metric = metric if isinstance(metric, str) else None
                    source_fields = [source_metric] if source_metric is not None else []
                rows.append({"symbol": selected[0]["symbol"], "source_symbol": source_symbol, "cik": selected[0]["cik"],
                             "native_source": provider, "statement": statement, "capture_position": capture_index,
                             "source_row_position": row, "source_period_end": end,
                             "source_period_original_json": _json(_original(label)), "source_row_count": 1,
                             "source_row_unit": "annual_report_row" if provider == AV else "metric_period_row",
                             "source_pin_json": _json(entry["pin"]),
                             "source_metric": source_metric, "source_fields_json": _json(source_fields),
                             "reason": "outside_selected_exact_ends" if end is not None else "unknown_source_end",
                             "target_period_assigned": False, "review_decision": "unreviewed",
                             "source_identity_status": "unverified"})
    return pd.DataFrame(rows, columns=["symbol", "source_symbol", "cik", "native_source", "statement", "capture_position",
                                       "source_row_position", "source_period_end", "source_period_original_json",
                                       "source_row_count", "source_row_unit", "source_pin_json", "reason",
                                       "source_metric", "source_fields_json", "target_period_assigned", "review_decision",
                                       "source_identity_status"])


def build_pilot_candidate_audit(contract, *, av_statements, yahoo_statements):
    """Return the fixed 354-cell/30-review denominators without source acceptance."""
    native, targets = _plan(contract)
    entries = _entries(av_statements, yahoo_statements, targets)
    coverage = []
    for target in targets:
        for declaration in native:
            provider, statement, field = (declaration[name] for name in ("native_source", "statement", "field"))
            symbol = target["symbol" if provider == AV else "yahoo_symbol"]
            captures = entries.get((provider, symbol, statement), [])
            candidates, field_seen = [], False
            for entry in captures:
                frame = entry["frame"]
                if provider == AV:
                    columns = [index for index, name in enumerate(frame.columns) if name == field]
                    field_seen |= bool(columns)
                    for row, (_, end) in enumerate(entry["periods"]):
                        if end == target["target_end"]:
                            candidates.extend(_candidate(entry, row, provider, field, column) for column in columns or [None])
                else:
                    for row, (_, end) in enumerate(entry["periods"]):
                        metric = _cell(frame, row, "source_metric")
                        if isinstance(metric, str) and metric == "annual" + field:
                            field_seen = True
                            if end == target["target_end"]:
                                candidates.append(_candidate(entry, row, provider, field))
            if not captures:
                presence, alignment = "not_captured", "not_captured"
            elif len(candidates) > 1:
                presence, alignment = "ambiguous", "exact_end"
            elif candidates:
                presence, alignment = candidates[0]["presence_status"], "exact_end"
            else:
                presence = "unavailable" if field_seen or all(item["frame"].empty for item in captures) else "field_absent"
                alignment = "no_exact_end" if field_seen else "no_field_observation"
            frequencies = {item["period_frequency_status"] for item in candidates}
            frequency = "annual_scope_mismatch" if "annual_scope_mismatch" in frequencies else (
                next(iter(frequencies)) if len(frequencies) == 1 else "ambiguous_frequency_evidence" if frequencies
                else "annual_requested_not_certified" if provider == AV and captures else "unknown")
            coverage.append({**{name: value for name, value in target.items() if name != "yahoo_symbol"}, **declaration,
                             "source_symbol": symbol, "presence_status": presence, "end_alignment": alignment,
                             "flow_start_status": "stock_instant_not_applicable" if statement in {"BALANCE_SHEET", "balance-sheet"}
                             else "unknown", "period_frequency_status": frequency,
                             "currency_evidence": _json([item["currency_evidence"] for item in candidates]),
                             "unit_scope_status": "units_scope_unverified", "version_status": "source_version_unreviewed",
                             "source_identity_status": "unverified",
                             "source_candidate_count": len(candidates), "review_decision": "unreviewed",
                             "source_acceptance": "none", "source_candidates_json": _json(candidates)})
    cells = pd.DataFrame(coverage)
    queue = []
    for target in targets:
        for concept, definition in contract["candidate_concepts"].items():
            subset = cells.loc[(cells.symbol == target["symbol"]) & (cells.fiscal_year == target["fiscal_year"])
                               & (cells.concept == concept)]
            queue.append({**{name: value for name, value in target.items() if name != "yahoo_symbol"}, "concept": concept,
                          "native_candidate_cells": len(subset), "ambiguous_cells": int(subset.presence_status.eq("ambiguous").sum()),
                          "finite_presence_cells": int(subset.presence_status.isin(["finite_candidate", "explicit_zero"]).sum()),
                          "review_scope": "alternate_candidates_not_all_required_scoring_inputs",
                          "required_scoring_inputs_complete": False, "review_decision": "unreviewed",
                          "source_acceptance": "none", "acceptance_rule": definition.get("acceptance", "unreviewed")})
    return {"coverage_cells": cells, "review_queue": pd.DataFrame(queue),
            "unmatched_source_periods": _unmatched(entries, targets, native)}
