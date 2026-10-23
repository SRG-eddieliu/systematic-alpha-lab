"""Availability keeps failed primary jobs, exact periods and unreviewed scope."""
from copy import deepcopy

import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline.statement_availability import CORE_FIELDS, FUNCTIONS, build_gap_coverage


def inputs():
    contract = {"contract_id": "bxp_doc_statement_availability_v1", "targets": [
        {"symbol": symbol, "cik": cik, "latest_annual_start": "2025-01-01", "latest_annual_end": "2025-12-31",
         "merger_effective_date": "2024-03-01"} for symbol, cik in (("BXP", "0001037540"), ("DOC", "0000765880"))]}
    primary = [{"request": {"symbol": symbol, "function": function}, "status": "failed", "pin": None,
                "job_id": symbol + ":" + function} for symbol in ("BXP", "DOC") for function in FUNCTIONS]
    jobs = [{"symbol": symbol, "statement": statement, "frequency": freq, "status": "captured"}
            for symbol in ("BXP", "DOC") for statement in FUNCTIONS.values() for freq in ("yearly", "quarterly")]
    statements = {}
    for job in jobs:
        symbol, statement, freq = (job[name] for name in ("symbol", "statement", "frequency"))
        prefix, end = ("annual", "2025-12-31") if freq == "yearly" else ("quarterly", "2026-06-30")
        frame = pd.DataFrame([{"source_metric": prefix + metric, "period_end": pd.Timestamp(end, tz="UTC"),
                               "source_value_json": "9007199254740993", "source_value_type": "integer",
                               "value_status": "reported_numeric", "source_period_type": "12M" if freq == "yearly" else "3M",
                               "provider": "yahoo_financial_timeseries", "symbol": symbol}
                              for metric in CORE_FIELDS[statement]])
        pin = {"provider": "yahoo_financial_timeseries", "snapshot_id": "synthetic",
               "request": {"symbol": symbol, "statement": statement, "frequency": freq}}
        statements[symbol, statement, freq] = {"frame": frame, "pin": pin}
    return contract, primary, jobs, statements


def build(contract, primary, jobs, statements):
    return build_gap_coverage(contract, statements=statements, primary_jobs=primary, logical_jobs=jobs)


def test_six_readable_candidates_leave_primary_and_semantics_unchanged():
    contract, primary, jobs, statements = inputs()
    original = deepcopy(primary)
    result = build(contract, primary, jobs, statements)
    assert len(result["coverage"]) == 6 and len(result["periods"]) == 12
    assert result["coverage"].availability_status.eq("readable_supplement_candidate").all()
    assert not result["coverage"].primary_overwritten.any()
    assert result["coverage"].semantic_acceptance.eq("unreviewed").all()
    assert primary == original


def test_missing_sources_and_not_attempted_jobs_keep_denominator():
    contract, primary, jobs, _ = inputs()
    for job in jobs:
        job["status"] = "not_attempted"
    result = build(contract, primary, jobs, {})
    assert len(result["coverage"]) == 6 and result["periods"].empty
    assert result["coverage"].availability_status.eq("partial_or_unavailable").all()


@pytest.mark.parametrize("alteration", ["missing_core", "duplicate_core", "wrong_annual_end", "legacy_quarter"])
def test_core_fields_must_share_an_exact_current_period(alteration):
    contract, primary, jobs, statements = inputs()
    key = ("DOC", "income", "quarterly" if alteration == "legacy_quarter" else "yearly")
    frame = statements[key]["frame"]
    if alteration == "missing_core":
        statements[key]["frame"] = frame.iloc[:1]
    elif alteration == "duplicate_core":
        statements[key]["frame"] = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    else:
        frame["period_end"] = pd.Timestamp("2023-12-31" if alteration == "legacy_quarter" else "2025-12-30", tz="UTC")
    result = build(contract, primary, jobs, statements)
    row = result["coverage"].loc[lambda x: x.symbol.eq("DOC") & x.source_function.eq("INCOME_STATEMENT")].iloc[0]
    assert row.availability_status == "partial_or_unavailable"
    if alteration == "legacy_quarter":
        assert result["periods"].issuer_period_status.eq("pre_merger_ticker_history_unreviewed").any()


@pytest.mark.parametrize("source_type,value,status", [
    ("boolean", "true", "reported_numeric"), ("float", "NaN", "reported_numeric"),
    ("null", "null", "source_null"), ("integer", "1", "absent"),
])
def test_invalid_or_missing_core_values_do_not_make_a_statement_ready(source_type, value, status):
    contract, primary, jobs, statements = inputs()
    frame = statements["BXP", "income", "yearly"]["frame"]
    frame.loc[0, ["source_value_type", "source_value_json", "value_status"]] = [source_type, value, status]
    result = build(contract, primary, jobs, statements)
    assert result["coverage"].availability_status.eq("readable_supplement_candidate").sum() == 5


@pytest.mark.parametrize("change", ["primary_success", "missing_primary", "missing_job", "wrong_source_pin", "wrong_symbol"])
def test_mismatched_primary_or_source_scope_rejected(change):
    contract, primary, jobs, statements = inputs()
    if change == "primary_success":
        primary[0]["status"] = "success"
    elif change == "missing_primary":
        primary.pop()
    elif change == "missing_job":
        jobs.pop()
    elif change == "wrong_source_pin":
        statements["DOC", "income", "yearly"]["pin"]["request"]["symbol"] = "PEAK"
    else:
        statements["DOC", "income", "yearly"]["frame"]["symbol"] = "OTHER"
    with pytest.raises(ValueError):
        build(contract, primary, jobs, statements)
