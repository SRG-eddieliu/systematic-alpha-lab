"""Candidate statement availability for explicit, still-failed primary jobs.

Readability, native core-field presence, issuer history and accounting acceptance
are separate. Nothing here replaces a primary observation or certifies a field.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

import pandas as pd

FUNCTIONS = {"INCOME_STATEMENT": "income", "BALANCE_SHEET": "balance-sheet", "CASH_FLOW": "cash-flow"}
FREQUENCIES = {"yearly": "annual", "quarterly": "quarterly"}
CORE_FIELDS = {
    "income": ("TotalRevenue", "NetIncome"),
    "balance-sheet": ("TotalAssets", "TotalLiabilitiesNetMinorityInterest"),
    "cash-flow": ("OperatingCashFlow", "InvestingCashFlow", "FinancingCashFlow"),
}


def _json(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


def _numeric(row):
    if row.get("value_status") != "reported_numeric" or row.get("source_value_type") not in {"integer", "float"}:
        return False
    try:
        return Decimal(row["source_value_json"]).is_finite()
    except (InvalidOperation, ValueError, TypeError):
        return False


def build_gap_coverage(contract, *, statements, primary_jobs, logical_jobs):
    """Return six primary/fallback decisions and explicit source-period coverage.

    ``statements`` maps (symbol, statement, frequency) to a facts frame and an
    exact reader metadata pin. Core fields are native presence probes only.
    """
    if contract.get("contract_id") != "bxp_doc_statement_availability_v1":
        raise ValueError("Require the explicit two-company gap contract")
    targets = {row["symbol"]: row for row in contract["targets"]}
    if set(targets) != {"BXP", "DOC"} or len(contract["targets"]) != 2:
        raise ValueError("This completion is limited to BXP and current DOC")
    expected_jobs = {(symbol, function) for symbol in targets for function in FUNCTIONS}
    primary = {(row["request"]["symbol"], row["request"]["function"]): row for row in primary_jobs}
    if set(primary) != expected_jobs or len(primary_jobs) != 6 or any(
        row["status"] != "failed" or row.get("pin") is not None for row in primary_jobs
    ):
        raise ValueError("Fallback is allowed only for the six explicitly failed primary jobs")
    allowed = {(symbol, statement, frequency) for symbol in targets for statement in FUNCTIONS.values()
               for frequency in FREQUENCIES}
    if set(statements) - allowed:
        raise ValueError("Unexpected company, statement or frequency")
    attempts = {(row["symbol"], row["statement"], row["frequency"]): row for row in logical_jobs}
    if set(attempts) != allowed or len(logical_jobs) != 12:
        raise ValueError("Retain the complete twelve-call denominator, including unattempted jobs")
    periods, summaries = [], {}
    for key in sorted(allowed):
        symbol, statement, frequency = key
        supplied = statements.get(key)
        state = {"source_readable": False, "numeric_fact_rows": 0, "source_periods": [],
                 "core_complete_periods": [], "latest_core_complete_period": None,
                 "latest_annual_target_present": False, "attempt_status": attempts[key]["status"], "pin": None}
        summaries[key] = state
        if supplied is None:
            continue
        frame, pin = supplied["frame"], supplied["pin"]
        if not isinstance(frame, pd.DataFrame) or not isinstance(pin, dict):
            raise TypeError("Require stored source facts and exact reader metadata")
        request = pin["request"]
        if (pin["provider"] != "yahoo_financial_timeseries" or pin.get("normalizer") != "yf_statement_http_v2"
                or request.get("schema") != "yf_statement_http_capture_v2" or any(
            request.get(name) != value for name, value in (("symbol", symbol), ("statement", statement),
                                                          ("frequency", frequency))
        )):
            raise ValueError("Source pin differs from the explicit availability selection")
        required = {"source_metric", "period_end", "source_value_json", "source_value_type", "value_status"}
        if not required.issubset(frame.columns):
            raise ValueError("Source facts schema missing")
        for name, value in (("symbol", symbol), ("provider", "yahoo_financial_timeseries"),
                            ("source_statement", statement), ("source_frequency", frequency),
                            ("normalizer", pin["normalizer"]), ("snapshot_id", pin["snapshot_id"])):
            if name in frame and not frame[name].eq(value).fillna(False).all():
                raise ValueError("Source rows differ from their availability selection")
        dates = pd.to_datetime(frame.period_end, utc=True, errors="raise")
        period_labels = sorted(dates.dropna().dt.strftime("%Y-%m-%d").unique().tolist())
        state.update(source_periods=period_labels, pin=pin)
        numeric = [_numeric(row) for row in frame.to_dict("records")]
        state["numeric_fact_rows"] = sum(numeric)
        state["source_readable"] = bool(state["numeric_fact_rows"])
        for label in period_labels:
            selected = frame.loc[dates.dt.strftime("%Y-%m-%d").eq(label)]
            numeric_rows = [row for row in selected.to_dict("records") if _numeric(row)]
            metric_counts = {}
            for row in numeric_rows:
                metric_counts[row["source_metric"]] = metric_counts.get(row["source_metric"], 0) + 1
            fields = CORE_FIELDS[statement]
            expected = [FREQUENCIES[frequency] + field for field in fields]
            missing = [field for field, metric in zip(fields, expected) if metric_counts.get(metric, 0) == 0]
            duplicate = [field for field, metric in zip(fields, expected) if metric_counts.get(metric, 0) > 1]
            expected_type = "12M" if frequency == "yearly" else "3M"
            type_conflicts = [field for field, metric in zip(fields, expected) if any(
                not isinstance(row.get("source_period_type"), str) or row["source_period_type"] != expected_type
                for row in numeric_rows
                if row["source_metric"] == metric
            )]
            complete = not missing and not duplicate and not type_conflicts
            if complete:
                state["core_complete_periods"].append(label)
            history = "source_period_issuer_unreviewed"
            if symbol == "DOC" and label < targets[symbol].get("merger_effective_date", "2024-03-01"):
                history = "pre_merger_ticker_history_unreviewed"
            periods.append({"symbol": symbol, "cik": targets[symbol]["cik"], "source_statement": statement,
                            "source_frequency": frequency, "period_end": pd.Timestamp(label, tz="UTC"),
                            "numeric_fact_rows": len(numeric_rows), "native_core_fields_present": complete,
                            "missing_core_fields_json": _json(missing), "duplicate_core_fields_json": _json(duplicate),
                            "core_period_type_conflicts_json": _json(type_conflicts),
                            "frequency_label_status": "missing_or_conflicting" if type_conflicts else "matching_source_label_duration_unverified",
                            "source_period_type_labels_json": _json(sorted(selected.source_period_type.dropna().unique().tolist()))
                            if "source_period_type" in selected else "[]",
                            "flow_start_status": "instant" if statement == "balance-sheet" else "unknown",
                            "issuer_period_status": history, "unit_scope_status": "unverified",
                            "semantic_acceptance": "unreviewed", "source_pin_json": _json(pin)})
        complete_periods = state["core_complete_periods"]
        state["latest_core_complete_period"] = complete_periods[-1] if complete_periods else None
        state["latest_annual_target_present"] = targets[symbol]["latest_annual_end"] in complete_periods
    rows = []
    for symbol, target in targets.items():
        for function, statement in FUNCTIONS.items():
            annual = summaries[symbol, statement, "yearly"]
            quarterly = summaries[symbol, statement, "quarterly"]
            recent_quarter = quarterly["latest_core_complete_period"] is not None and (
                quarterly["latest_core_complete_period"] >= target["latest_annual_start"]
            )
            candidate = annual["latest_annual_target_present"] and recent_quarter
            rows.append({"symbol": symbol, "cik": target["cik"], "source_function": function,
                         "primary_provider": "alpha_vantage", "primary_original_status": primary[symbol, function]["status"],
                         "primary_original_job_id": primary[symbol, function]["job_id"], "primary_overwritten": False,
                         "supplement_provider": "yahoo_financial_timeseries", "annual_readable": annual["source_readable"],
                         "quarterly_readable": quarterly["source_readable"],
                         "latest_annual_native_core_present": annual["latest_annual_target_present"],
                         "recent_quarter_native_core_present": recent_quarter,
                         "availability_status": "readable_supplement_candidate" if candidate else "partial_or_unavailable",
                         "annual_periods_json": _json(annual["source_periods"]),
                         "quarterly_periods_json": _json(quarterly["source_periods"]),
                         "annual_pin_json": _json(annual["pin"]), "quarterly_pin_json": _json(quarterly["pin"]),
                         "annual_attempt_status": annual["attempt_status"], "quarterly_attempt_status": quarterly["attempt_status"],
                         "entity_binding": "contract_declared_current_mapping; provider_symbol_only",
                         "historical_issuer_binding": "unreviewed", "accounting_scope": "unreviewed",
                         "semantic_acceptance": "unreviewed", "historical_availability": "not_certified"})
    columns = ["symbol", "cik", "source_statement", "source_frequency", "period_end", "numeric_fact_rows",
               "native_core_fields_present", "missing_core_fields_json", "duplicate_core_fields_json",
               "core_period_type_conflicts_json", "frequency_label_status", "source_period_type_labels_json",
               "flow_start_status", "issuer_period_status", "unit_scope_status",
               "semantic_acceptance", "source_pin_json"]
    return {"coverage": pd.DataFrame(rows), "periods": pd.DataFrame(periods, columns=columns)}
