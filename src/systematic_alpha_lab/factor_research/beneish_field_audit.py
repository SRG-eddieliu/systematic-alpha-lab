"""Aggregate candidate-field coverage from explicitly pinned offline AV tables.

This research audit neither collects nor normalizes data. Finite source amounts
do not establish accounting equivalence, calculator eligibility or as-of fitness.
No amounts, provider symbols, source identities, dates or paths are returned.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from numbers import Real

import pandas as pd

from .beneish_pipeline import AV_CANDIDATES, FUNCTIONS, NORMALIZER
from .beneish_standard import DEFINITION_ID

AUDIT_VERSION = "beneish_field_coverage_v2"
TABLES = ("annual", "quarterly")
_MISSING_MARKERS = {"", "none", "null"}
_ALTERNATIVES = {
    "INCOME_STATEMENT": {
        "costOfRevenue": "scope_equivalence_unverified",
        "depreciationAndAmortization": "not_pure_depreciation_not_standard_accepted",
        "netIncome": "not_ibei_without_verified_bridge",
        "netIncomeFromContinuingOperations": "not_ibei_without_verified_bridge",
        "incomeBeforeTax": "not_ibei_not_standard_accepted",
        "incomeTaxExpense": "tax_component_not_ibei_without_verified_bridge",
    },
    "BALANCE_SHEET": {
        "longTermDebt": "scope_equivalence_unverified",
        "currentLongTermDebt": "current_maturities_not_noncurrent_debt",
        "currentDebt": "broad_debt_not_noncurrent_debt",
        "shortLongTermDebtTotal": "broad_debt_not_noncurrent_debt",
        "capitalLeaseObligations": "scope_equivalence_unverified",
        "accumulatedDepreciationAmortizationPPE": "stock_not_current_pure_depreciation_expense",
    },
    "CASH_FLOW": {
        "depreciationDepletionAndAmortization": "not_pure_depreciation_not_standard_accepted",
        "netIncome": "not_ibei_without_verified_bridge",
        "profitLoss": "consolidated_vs_parent_income_scope_unverified_not_ibei",
    },
}
_UNPROMISED_COMPONENT_PROBES = {"INCOME_STATEMENT": ("amortization", "depletion")}
_ROW_BUCKETS = (
    "column_absent_rows", "missing_marker_rows", "invalid_numeric_rows",
    "nonfinite_numeric_rows", "boolean_rows", "finite_rows",
)
_METADATA_COLUMNS = ("asset_id", "available_at", "period_start", "fiscal_year")
_METADATA_STATES = {
    "amount_unit_status": ("unverified", "verified", "not_supplied"),
    "flow_basis": ("stock", "annual", "quarterly", "ytd", "unverified", "not_supplied"),
}


def _amount(value):
    """Keep scalar decimal finiteness distinct from float calculator eligibility.

    Native and textual NaN/Infinity are nonfinite, not null markers. Pandas NA
    and NaT are null markers. An omitted key already materialized as numeric NaN
    cannot be distinguished from native NaN here; no source field is repaired.
    """
    if value is None or value is pd.NA or value is pd.NaT:
        return "missing_marker_rows", None
    if not pd.api.types.is_scalar(value):
        return "invalid_numeric_rows", None
    if isinstance(value, bool) or getattr(getattr(value, "dtype", None), "kind", None) == "b":
        return "boolean_rows", None
    if isinstance(value, str):
        value = value.strip()
        if value.lower() in _MISSING_MARKERS:
            return "missing_marker_rows", None
    elif not isinstance(value, (Real, Decimal)):
        return "invalid_numeric_rows", None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "invalid_numeric_rows", None
    if not number.is_finite():
        return "nonfinite_numeric_rows", None
    return "finite_rows", number


def _validate_selections(selections):
    if not isinstance(selections, list) or not selections:
        raise ValueError("Declare a nonempty list of pinned source selections")
    result, identities = [], set()
    for selection in selections:
        if not isinstance(selection, Mapping) or set(selection) != {"symbol", "function", "snapshot_id"}:
            raise ValueError("Each selection requires exactly symbol, function and snapshot_id")
        symbol, function, snapshot_id = (selection[name] for name in ("symbol", "function", "snapshot_id"))
        if not isinstance(symbol, str) or re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol) is None:
            raise ValueError("Invalid explicit provider symbol")
        if not isinstance(function, str) or function not in FUNCTIONS:
            raise ValueError("Unsupported statement function")
        if not isinstance(snapshot_id, str) or re.fullmatch(r"[0-9a-f]{32}", snapshot_id) is None:
            raise ValueError("Invalid pinned snapshot identifier")
        if (symbol, function) in identities:
            raise ValueError("Duplicate provider symbol/function selection")
        identities.add((symbol, function))
        result.append(dict(selection))
    return sorted(result, key=lambda item: (FUNCTIONS.index(item["function"]), item["symbol"]))


def _validate_read(read, selection, table):
    metadata, frame = getattr(read, "metadata", None), getattr(read, "frame", None)
    expected = {
        "snapshot_id": selection["snapshot_id"], "normalizer": NORMALIZER, "table": table,
        "provider": "alpha_vantage", "request": {"function": selection["function"], "symbol": selection["symbol"]},
    }
    if not isinstance(metadata, Mapping) or any(metadata.get(key) != value for key, value in expected.items()):
        raise ValueError("Returned source identity differs from the pinned selection")
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique:
        raise ValueError("Returned statement must have unique source columns")
    if any(type(metadata.get(key)) is not int or metadata[key] != len(frame) for key in ("source_rows", "returned_rows")):
        raise ValueError("Returned statement is not the complete pinned source table")
    identities = {
        "snapshot_id": selection["snapshot_id"], "normalizer": NORMALIZER, "provider": "alpha_vantage",
        "symbol": selection["symbol"], "source_function": selection["function"], "period_type": table,
    }
    if any(name not in frame or not frame[name].eq(value).fillna(False).all() for name, value in identities.items()):
        raise ValueError("Statement row source identity differs from its pinned metadata")
    return frame


def _period_counts(frame):
    counts = {"period_column_absent_tables": int("period_end" not in frame), "missing_period_rows": 0,
              "invalid_period_rows": 0, "duplicate_period_rows": 0, "duplicate_period_excess_rows": 0}
    if "period_end" not in frame:
        counts["missing_period_rows"] = len(frame)
        return counts
    periods = []
    for value in frame["period_end"]:
        if value is None or value is pd.NA or value is pd.NaT or (
            isinstance(value, str) and value.strip().lower() in _MISSING_MARKERS
        ) or (isinstance(value, Real) and pd.isna(value)):
            counts["missing_period_rows"] += 1
            continue
        if not isinstance(value, (str, date, datetime, pd.Timestamp)):
            counts["invalid_period_rows"] += 1
            continue
        try:
            stamp = pd.Timestamp(value)
            stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
            if pd.isna(stamp) or stamp != stamp.normalize():
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            counts["invalid_period_rows"] += 1
            continue
        periods.append(stamp)
    frequencies = Counter(periods)
    counts["duplicate_period_rows"] = sum(count for count in frequencies.values() if count > 1)
    counts["duplicate_period_excess_rows"] = sum(count - 1 for count in frequencies.values() if count > 1)
    return counts


def _empty_metadata(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_MARKERS
    return isinstance(value, Real) and bool(pd.isna(value))


def _field_definitions(function):
    definitions = {}
    for canonical, (source, field) in AV_CANDIDATES.items():
        if source == function:
            constraint = "candidate_semantics_not_verified"
            if canonical == "trade_receivables_net":
                constraint = "broader_receivables_proxy_until_trade_equivalence_verified"
            elif canonical == "income_before_extraordinary_items":
                constraint = "probed_field_not_certified_direct_mapping"
            definitions[field] = {"canonical_fields": [canonical], "candidate_role": "canonical_candidate",
                                  "acceptance_constraint": constraint}
    for field, constraint in _ALTERNATIVES[function].items():
        definitions[field] = {"canonical_fields": [], "candidate_role": "alternative_candidate",
                              "acceptance_constraint": constraint}
    for field in _UNPROMISED_COMPONENT_PROBES.get(function, ()):
        definitions[field] = {
            "canonical_fields": [], "candidate_role": "probed_unpromised_component",
            "acceptance_constraint": "no_official_mapping_or_coverage_promised_not_standard_accepted",
        }
    return definitions


def _new_group(function, table, denominator):
    fields = {}
    for field, definition in _field_definitions(function).items():
        fields[field] = {
            **definition, "semantic_status": "unverified_not_standard_accepted", "source_rows": 0,
            **dict.fromkeys(_ROW_BUCKETS, 0), "column_absent_tables": 0,
            "positive_rows": 0, "zero_rows": 0, "negative_rows": 0,
            "provider_symbols_with_finite": 0, "provider_symbol_denominator": denominator,
        }
    group = {
        "function": function, "table": table, "source_tables": 0, "source_rows": 0,
        "provider_symbol_denominator": denominator, "fields": fields,
        "period_quality": dict.fromkeys(_period_counts(pd.DataFrame()), 0),
        "metadata_coverage": {
            **{name: {"column_present_tables": 0, "nonempty_rows": 0} for name in _METADATA_COLUMNS},
            **{name + "_counts": dict.fromkeys((*states, "other", "missing", "column_absent"), 0)
               for name, states in _METADATA_STATES.items()},
        },
    }
    if function == "BALANCE_SHEET":
        group["conditional_debt_diagnostic"] = {
            "status": "conditional_derivation_only_not_standard_accepted",
            "minuend": "longTermDebt", "subtrahend": "currentLongTermDebt",
            "source_rows": 0, "jointly_finite_rows": 0,
            "difference_nonnegative_rows": 0, "difference_negative_rows": 0,
            "negative_component_rows": 0, "both_components_nonnegative_rows": 0,
            "standard_field_filled": False,
        }
    if function == "CASH_FLOW":
        group["cash_flow_income_comparison"] = {
            "status": "not_IBEI_verification", "left_field": "netIncome", "right_field": "profitLoss",
            "comparison_basis": "same_source_statement_row_no_cause_inference",
            "source_rows": 0, "jointly_finite_rows": 0, "equal_rows": 0, "different_rows": 0,
            "standard_field_filled": False,
        }
    return group


def _add_frame(group, frame):
    group["source_tables"] += 1
    group["source_rows"] += len(frame)
    for name, count in _period_counts(frame).items():
        group["period_quality"][name] += count
    for name in _METADATA_COLUMNS:
        if name in frame:
            group["metadata_coverage"][name]["column_present_tables"] += 1
            group["metadata_coverage"][name]["nonempty_rows"] += sum(not _empty_metadata(value) for value in frame[name])
    for name, states in _METADATA_STATES.items():
        counts = group["metadata_coverage"][name + "_counts"]
        if name not in frame:
            counts["column_absent"] += len(frame)
        else:
            for value in frame[name]:
                state = "missing" if _empty_metadata(value) else value if isinstance(value, str) and value in states else "other"
                counts[state] += 1
    parsed = {}
    for field, counts in group["fields"].items():
        counts["source_rows"] += len(frame)
        if field not in frame:
            counts["column_absent_tables"] += 1
            counts["column_absent_rows"] += len(frame)
            continue
        values = [_amount(value) for value in frame[field]]
        parsed[field] = values
        finite_symbol = False
        for bucket, value in values:
            counts[bucket] += 1
            if value is not None:
                finite_symbol = True
                counts["positive_rows" if value > 0 else "negative_rows" if value < 0 else "zero_rows"] += 1
        counts["provider_symbols_with_finite"] += int(finite_symbol)
    if "conditional_debt_diagnostic" in group:
        counts = group["conditional_debt_diagnostic"]
        counts["source_rows"] += len(frame)
        if {"longTermDebt", "currentLongTermDebt"}.issubset(parsed):
            for (_, total), (_, current) in zip(parsed["longTermDebt"], parsed["currentLongTermDebt"]):
                if total is not None and current is not None:
                    counts["jointly_finite_rows"] += 1
                    # Compare exactly instead of subtracting under a Decimal context.
                    counts["difference_nonnegative_rows" if total >= current else "difference_negative_rows"] += 1
                    counts["negative_component_rows" if total < 0 or current < 0
                           else "both_components_nonnegative_rows"] += 1
    if "cash_flow_income_comparison" in group:
        counts = group["cash_flow_income_comparison"]
        counts["source_rows"] += len(frame)
        if {"netIncome", "profitLoss"}.issubset(parsed):
            for (_, net_income), (_, profit_loss) in zip(parsed["netIncome"], parsed["profitLoss"]):
                if net_income is not None and profit_loss is not None:
                    counts["jointly_finite_rows"] += 1
                    # Equality needs neither subtraction nor float conversion;
                    # it does not identify why the two reported values differ.
                    counts["equal_rows" if net_income == profit_loss else "different_rows"] += 1


def audit_beneish_field_coverage(reader, *, selections):
    """Read annual and quarterly candidate fields through OfflineDataReader.read.

    Selections are a nonempty list of exact symbol/function/snapshot_id objects;
    partial endpoint coverage is allowed, duplicate symbol/function choices are
    rejected before reading. Both tables must be materialized for every selected
    source; read failures propagate rather than silently shrinking denominators.
    Each function/table denominator includes all its selected provider symbols,
    even an empty table or a symbol with no finite field values. These are source
    statement rows, never aligned research rows or counts of eligible scores.

    Row buckets partition every field's source_rows. Missing columns count every
    row plus an absent-table counter. Null/empty/None/null markers, booleans,
    invalid numerics, nonfinite numerics and finite decimals stay distinct. Finite
    decimals can exceed float calculator limits. No canonical value is created,
    D&A is not pure depreciation, and conditional debt diagnostics fill nothing.
    Unpromised amortization/depletion probes carry no official mapping or
    coverage assertion. CF income comparisons stay within the same source row;
    equality/difference neither establishes IBEI nor explains a scope difference.
    The caller supplies a closed, quiescent root; this function never discovers
    latest versions, requests credentials, collects, writes, joins or calculates M.
    """
    selected = _validate_selections(selections)
    denominators = Counter(item["function"] for item in selected)
    groups = {(function, table): _new_group(function, table, denominators[function])
              for function in FUNCTIONS if function in denominators for table in TABLES}
    for selection in selected:
        for table in TABLES:
            read = reader.read(snapshot_id=selection["snapshot_id"], normalizer=NORMALIZER, table=table)
            frame = _validate_read(read, selection, table)
            _add_frame(groups[(selection["function"], table)], frame)
    return {
        "audit_version": AUDIT_VERSION, "definition_id": DEFINITION_ID, "normalizer": NORMALIZER,
        "selection_count": len(selected), "provider_symbol_count": len({item["symbol"] for item in selected}),
        "semantic_verification_status": "not_assessed", "standard_definition_satisfied": False,
        "factor_calculated": False, "research_ready": False,
        "metadata_gate_status": "not_assessed_nonempty_and_source_labels_do_not_verify_metadata",
        "annual_duration_status": "not_inferred_from_source_annual_label",
        "row_basis": "source_statement_rows_not_aligned_research_rows",
        "finite_policy": "decimal_finite_parse_not_calculator_eligibility",
        "missing_marker_policy": "null_pandas_na_nat_or_trimmed_case_insensitive_empty_none_null",
        "nonfinite_policy": "native_or_text_nan_infinity_nonfinite_not_missing",
        "network_operations": "none_requested", "groups": list(groups.values()),
    }
