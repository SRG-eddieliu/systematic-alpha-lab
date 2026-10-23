"""Self-contained public synthetic contract; no source files or data services."""
from copy import deepcopy
import json
import socket

import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline.supplement_candidate_audit import AV, YAHOO, build_pilot_candidate_audit


@pytest.fixture
def contract():
    # Only public native field declarations are reproduced here. Issuer names,
    # symbols and CIKs below are synthetic and have no source-data dependencies.
    concepts = {
        "pure_depreciation_policy": {
            "av_fields": {"INCOME_STATEMENT": ["depreciation"]},
            "yahoo_income_fields": ["DepreciationIncomeStatement"], "yahoo_cash_flow_fields": ["Depreciation"]},
        "paper_dp_minus_am_target": {
            "av_fields": {"INCOME_STATEMENT": ["depreciationAndAmortization"],
                          "CASH_FLOW": ["depreciationDepletionAndAmortization"]},
            "yahoo_income_fields": ["DepreciationAmortizationDepletionIncomeStatement", "DepletionIncomeStatement",
                                    "DepreciationAndAmortizationInIncomeStatement", "Amortization",
                                    "AmortizationOfIntangiblesIncomeStatement"],
            "yahoo_cash_flow_fields": ["DepreciationAmortizationDepletion", "Depletion", "DepreciationAndAmortization",
                                       "AmortizationCashFlow", "AmortizationOfIntangibles"]},
        "noncurrent_debt_and_lease_scope": {
            "av_fields": {"BALANCE_SHEET": ["longTermDebtNoncurrent", "longTermDebt", "currentLongTermDebt",
                                             "currentDebt", "capitalLeaseObligations"]},
            "yahoo_balance_sheet_fields": ["LongTermDebt", "LongTermDebtAndCapitalLeaseObligation",
                                            "LongTermCapitalLeaseObligation", "CapitalLeaseObligations", "CurrentDebt",
                                            "CurrentDebtAndCapitalLeaseObligation", "CurrentCapitalLeaseObligation",
                                            "CurrentLiabilities"]},
        "ib18_income_bridge": {
            "av_fields": {"INCOME_STATEMENT": ["netIncome", "netIncomeFromContinuingOperations", "incomeBeforeTax",
                                                "incomeTaxExpense"],
                          "CASH_FLOW": ["netIncome", "profitLoss", "operatingCashflow"]},
            "yahoo_income_fields": ["NetIncomeFromContinuingOperationNetMinorityInterest", "NetIncomeContinuousOperations",
                                     "NetIncome", "NetIncomeIncludingNoncontrollingInterests", "MinorityInterests",
                                     "NetIncomeDiscontinuousOperations", "NetIncomeExtraordinary", "NetIncomeCommonStockholders",
                                     "PreferredStockDividends", "PretaxIncome", "TaxProvision", "SpecialIncomeCharges"],
            "yahoo_cash_flow_fields": ["NetIncomeFromContinuingOperations", "OperatingCashFlow",
                                       "CashFlowFromContinuingOperatingActivities", "CashFromDiscontinuedOperatingActivities"]},
        "receivables_scope_check": {
            "av_fields": {"BALANCE_SHEET": ["currentNetReceivables"]},
            "yahoo_balance_sheet_fields": ["AccountsReceivable", "Receivables", "OtherReceivables", "NotesReceivable",
                                            "LoansReceivable", "AllowanceForDoubtfulAccountsReceivable", "GrossAccountsReceivable"]},
    }
    periods = [{"fiscal_year": 2024, "period_start": "2023-10-01", "period_end": "2024-09-28"},
               {"fiscal_year": 2025, "period_start": "2024-09-29", "period_end": "2025-09-27"}]
    return {"contract_id": "av_primary_supplement_pilot_v1", "candidate_concepts": concepts, "scope": {"issuers": [
        {"av_symbol": symbol, "yahoo_symbol": symbol, "cik": str(number).zfill(10), "periods": deepcopy(periods)}
        for number, symbol in enumerate(("SYNTHA", "SYNTHB", "SYNTHC"), 1)
    ]}}


def one_cell(result, provider=AV, statement="INCOME_STATEMENT", field="depreciation", year=2024):
    cells = result["coverage_cells"]
    selected = cells.loc[(cells.symbol == "SYNTHA") & (cells.fiscal_year == year) & (cells.native_source == provider)
                         & (cells.statement == statement) & (cells.field == field)]
    assert len(selected) == 1
    return selected.iloc[0]


def av_source(values, ends=None, field="depreciation", **metadata):
    ends = ends or ["2024-09-28"] * len(values)
    frame = pd.DataFrame({"fiscalDateEnding": ends, field: pd.Series(values, dtype=object), **metadata}, dtype=object)
    return {"frame": frame, "pin": {"snapshot_id": "synthetic-av", "raw_sha256": "a" * 64}}


def yahoo_source(fields, ends, values, frequencies=None, **pin):
    return {"frame": pd.DataFrame({
        "source_metric": ["annual" + field for field in fields], "period_end": pd.to_datetime(ends, utc=True),
        "source_value_json": values, "source_value_type": ["integer"] * len(fields),
        "value_status": ["reported_numeric"] * len(fields), "currency": ["USD"] * len(fields),
        "source_period_type": frequencies or ["12M"] * len(fields),
    }), "pin": {"snapshot_id": "synthetic-yahoo", **pin}}


def test_empty_inputs_keep_full_native_and_review_denominators(contract, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("The candidate audit must not use network or source file I/O")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr("builtins.open", denied)
    result = build_pilot_candidate_audit(contract, av_statements={}, yahoo_statements={})
    cells, queue = result["coverage_cells"], result["review_queue"]
    assert len(cells) == 354 and len(queue) == 30 and result["unmatched_source_periods"].empty
    assert cells.groupby(["symbol", "fiscal_year"]).size().eq(59).all()
    assert cells.presence_status.eq("not_captured").all()
    assert cells.source_candidates_json.eq("[]").all() and cells.source_candidate_count.eq(0).all()
    assert cells.review_decision.eq("unreviewed").all() and cells.source_acceptance.eq("none").all()
    assert queue.review_scope.eq("alternate_candidates_not_all_required_scoring_inputs").all()
    assert not queue.required_scoring_inputs_complete.any()
    assert set(queue.native_candidate_cells) == {3, 12, 13, 23, 8}


def test_exact_periods_only_and_unknown_flow_start_even_with_annual_metadata(contract):
    av = av_source(["10.00", "11.00", "12.00"], ["2024-09-28", "2024-09-30", "2023-09-30"],
                   reportedCurrency=["USD"] * 3, period_start=["2023-10-01"] * 3)
    yahoo = yahoo_source(["Depreciation", "Depreciation", "OperatingCashFlow"],
                         ["2024-09-28", "2024-09-30", "2024-09-28"], ["15", "16", "0"],
                         frequencies=["12M", "12M", "3M"])
    result = build_pilot_candidate_audit(contract, av_statements={("SYNTHA", "INCOME_STATEMENT"): av},
                                          yahoo_statements={("SYNTHA", "cash-flow"): [yahoo]})
    cell = one_cell(result)
    assert cell.presence_status == "finite_candidate" and cell.end_alignment == "exact_end"
    assert cell.flow_start_status == "unknown" and cell.period_frequency_status == "annual_requested_not_certified"
    evidence = json.loads(cell.source_candidates_json)
    assert len(evidence) == 1 and evidence[0]["original_value"] == {"kind": "string", "value": "10.00"}
    assert evidence[0]["source_period_start_original"]["value"] == "2023-10-01"
    candidate = one_cell(result, YAHOO, "cash-flow", "Depreciation")
    assert candidate.period_frequency_status == "annual_label_unverified_duration" and candidate.flow_start_status == "unknown"
    mismatch = one_cell(result, YAHOO, "cash-flow", "OperatingCashFlow")
    assert mismatch.presence_status == "explicit_zero" and mismatch.period_frequency_status == "annual_scope_mismatch"
    unmatched = result["unmatched_source_periods"]
    assert len(unmatched) == unmatched.source_row_count.sum() == 3
    assert set(unmatched.source_period_end) == {"2024-09-30", "2023-09-30"}
    assert not unmatched.target_period_assigned.any()
    assert one_cell(result, year=2025).presence_status == "unavailable"


@pytest.mark.parametrize("value,status", [
    ("None", "missing_literal"), ("", "missing_literal"), (None, "source_null"), (pd.NA, "pandas_missing"),
    (0, "explicit_zero"), ("0.000", "explicit_zero"), (False, "boolean"), (True, "boolean"),
    (float("inf"), "nonfinite"), (float("nan"), "nonfinite"), ("Infinity", "nonfinite"),
    ("unparseable", "invalid_numeric"), (9007199254740993, "finite_candidate"),
])
def test_av_literal_missing_zero_boolean_nonfinite_and_integer_types_stay_distinct(contract, value, status):
    result = build_pilot_candidate_audit(contract, av_statements={("SYNTHA", "INCOME_STATEMENT"): av_source([value])},
                                          yahoo_statements={})
    cell = one_cell(result)
    assert cell.presence_status == status and cell.review_decision == "unreviewed"
    candidate = json.loads(cell.source_candidates_json)[0]
    if isinstance(value, int) and not isinstance(value, bool):
        assert candidate["original_value"] == {"kind": "integer", "value": value}
    if isinstance(value, str):
        assert candidate["original_value"] == {"kind": "string", "value": value}


def test_field_absence_and_empty_capture_do_not_remove_any_denominator(contract):
    source = {"frame": pd.DataFrame({"fiscalDateEnding": ["2024-09-28"], "other": [1]}), "pin": {}}
    result = build_pilot_candidate_audit(contract, av_statements={("SYNTHA", "INCOME_STATEMENT"): source,
                                                                   ("SYNTHA", "BALANCE_SHEET"): {"frame": pd.DataFrame(), "pin": {}}},
                                          yahoo_statements={})
    assert len(result["coverage_cells"]) == 354
    assert one_cell(result).presence_status == "field_absent"
    balance = one_cell(result, AV, "BALANCE_SHEET", "longTermDebt")
    assert balance.presence_status == "unavailable" and balance.flow_start_status == "stock_instant_not_applicable"


@pytest.mark.parametrize("frequency", ["TTM", "3M", "6M", "9M", "YTD", "quarterly"])
def test_exact_end_does_not_qualify_nonannual_frequency_candidates(contract, frequency):
    source = yahoo_source(["Depreciation"], ["2024-09-28"], ["999"], frequencies=[frequency])
    result = build_pilot_candidate_audit(contract, av_statements={},
                                          yahoo_statements={("SYNTHA", "cash-flow"): [source]})
    cell = one_cell(result, YAHOO, "cash-flow", "Depreciation")
    assert cell.end_alignment == "exact_end" and cell.presence_status == "finite_candidate"
    assert cell.period_frequency_status == "annual_scope_mismatch" and cell.source_acceptance == "none"


def test_no_same_month_or_year_nearest_mapping_and_no_invented_currency(contract):
    source = yahoo_source(["Depreciation"], ["2024-09-30"], ["1"])
    source["frame"]["currency"] = None
    result = build_pilot_candidate_audit(contract, av_statements={},
                                          yahoo_statements={("SYNTHA", "cash-flow"): [source]})
    cell = one_cell(result, YAHOO, "cash-flow", "Depreciation")
    assert cell.presence_status == "unavailable" and cell.end_alignment == "no_exact_end"
    assert cell.source_candidates_json == "[]" and cell.currency_evidence == "[]"
    unmatched = result["unmatched_source_periods"]
    assert "source_candidates_json" not in unmatched.columns
    assert unmatched.source_metric.iloc[0] == "annualDepreciation"
    assert json.loads(unmatched.source_fields_json.iloc[0]) == ["annualDepreciation"]
    assert json.loads(unmatched.source_pin_json.iloc[0]) == source["pin"]


def test_large_yahoo_numeric_lexeme_and_arbitrary_source_pins_are_retained_verbatim(contract):
    source = yahoo_source(["Depreciation", "Depreciation"], ["2024-09-28", "2025-09-27"],
                          ["9007199254740993123456789", "1.234567890123456789e2000"],
                          observed_at="synthetic-unreviewed-version", nested={"original": 9007199254740993})
    original = source["frame"].copy(deep=True)
    pin = deepcopy(source["pin"])
    result = build_pilot_candidate_audit(contract, av_statements={},
                                          yahoo_statements={("SYNTHA", "cash-flow"): [source]})
    for year, lexeme in ((2024, "9007199254740993123456789"), (2025, "1.234567890123456789e2000")):
        cell = one_cell(result, YAHOO, "cash-flow", "Depreciation", year)
        evidence = json.loads(cell.source_candidates_json)[0]
        assert evidence["source_value_json"] == {"kind": "string", "value": lexeme}
        assert evidence["pin"] == pin and cell.presence_status == "finite_candidate"
    pd.testing.assert_frame_equal(source["frame"], original)
    assert source["pin"] == pin


def test_duplicate_dates_and_http_chunk_candidates_are_ambiguous_without_latest_selection(contract):
    av = av_source([1, 2])
    av["frame"].index = [7, 7]
    first = yahoo_source(["Depreciation"], ["2024-09-28"], ["111"], observed_at="2001", snapshot_id="older")
    second = yahoo_source(["Depreciation"], ["2024-09-28"], ["222"], observed_at="2099", snapshot_id="newer")
    result = build_pilot_candidate_audit(contract, av_statements={("SYNTHA", "INCOME_STATEMENT"): av},
                                          yahoo_statements={("SYNTHA", "cash-flow"): [first, second]})
    for cell in (one_cell(result), one_cell(result, YAHOO, "cash-flow", "Depreciation")):
        assert cell.presence_status == "ambiguous" and cell.source_candidate_count == 2
        assert len(json.loads(cell.source_candidates_json)) == 2 and cell.review_decision == "unreviewed"
    assert [item["pin"]["snapshot_id"] for item in json.loads(
        one_cell(result, YAHOO, "cash-flow", "Depreciation").source_candidates_json)] == ["older", "newer"]


def test_duplicate_native_columns_remain_separate_candidates(contract):
    source = {"frame": pd.DataFrame([["2024-09-28", 1, 2]],
                                     columns=["fiscalDateEnding", "depreciation", "depreciation"]), "pin": {}}
    result = build_pilot_candidate_audit(contract, av_statements={("SYNTHA", "INCOME_STATEMENT"): source},
                                          yahoo_statements={})
    cell = one_cell(result)
    assert cell.presence_status == "ambiguous" and cell.source_candidate_count == 2
    assert [item["source_column_position"] for item in json.loads(cell.source_candidates_json)] == [1, 2]


def test_contract_and_inputs_are_not_mutated_and_unknown_source_periods_are_excluded(contract):
    before = deepcopy(contract)
    source = av_source(["1"], ends=["not-a-date"])
    frame_before = source["frame"].copy(deep=True)
    result = build_pilot_candidate_audit(contract, av_statements={("SYNTHA", "INCOME_STATEMENT"): source},
                                          yahoo_statements={})
    assert contract == before
    pd.testing.assert_frame_equal(source["frame"], frame_before)
    unmatched = result["unmatched_source_periods"]
    assert len(unmatched) == 1 and unmatched.reason.iloc[0] == "unknown_source_end"
    assert unmatched.source_period_end.iloc[0] is None


def test_scope_and_native_denominator_drift_are_rejected(contract):
    with pytest.raises(ValueError, match="outside"):
        build_pilot_candidate_audit(contract, av_statements={("OTHER", "INCOME_STATEMENT"): av_source([1])}, yahoo_statements={})
    changed = deepcopy(contract)
    changed["candidate_concepts"]["pure_depreciation_policy"]["av_fields"]["INCOME_STATEMENT"].append("other")
    with pytest.raises(ValueError, match="59"):
        build_pilot_candidate_audit(changed, av_statements={}, yahoo_statements={})


def test_nullable_yahoo_metadata_remains_unknown_and_is_not_silently_filled(contract):
    source = yahoo_source(["Depreciation"], ["2024-09-28"], [pd.NA])
    source["frame"]["source_value_type"] = pd.NA
    source["frame"]["source_period_type"] = pd.NA
    result = build_pilot_candidate_audit(contract, av_statements={},
                                          yahoo_statements={("SYNTHA", "cash-flow"): [source]})
    cell = one_cell(result, YAHOO, "cash-flow", "Depreciation")
    assert cell.presence_status == "field_absent" and cell.period_frequency_status == "unknown"
    assert json.loads(cell.source_candidates_json)[0]["source_value_json"]["kind"] == "pandas_na"


@pytest.mark.parametrize("provider,column,wrong", [
    (AV, "symbol", "OTHER"), (AV, "provider", YAHOO), (AV, "source_function", "CASH_FLOW"),
    (YAHOO, "symbol", "OTHER"), (YAHOO, "provider", AV), (YAHOO, "source_statement", "income"),
])
def test_source_identity_columns_cannot_be_routed_under_a_different_dictionary_key(contract, provider, column, wrong):
    source = av_source([1]) if provider == AV else yahoo_source(["Depreciation"], ["2024-09-28"], ["1"])
    source["frame"][column] = wrong
    av = {("SYNTHA", "INCOME_STATEMENT"): source} if provider == AV else {}
    yahoo = {("SYNTHA", "cash-flow"): [source]} if provider == YAHOO else {}
    with pytest.raises(ValueError, match="identity conflicts"):
        build_pilot_candidate_audit(contract, av_statements=av, yahoo_statements=yahoo)


@pytest.mark.parametrize("pin", [
    {"provider": YAHOO}, {"request": {"symbol": "OTHER"}}, {"request": {"function": "CASH_FLOW"}},
    {"request": {"statement": "BALANCE_SHEET"}},
])
def test_source_pin_identity_conflicts_are_rejected(contract, pin):
    source = av_source([1])
    source["pin"] = pin
    with pytest.raises(ValueError, match="identity conflicts"):
        build_pilot_candidate_audit(contract, av_statements={("SYNTHA", "INCOME_STATEMENT"): source}, yahoo_statements={})


def test_absent_identity_is_unverified_and_nonselected_rows_contain_no_financial_values(contract):
    source = yahoo_source(["Depreciation", "NotAContractField"], ["2023-09-30", "2024-09-30"],
                          ["987654321999999", "876543210999999"])
    result = build_pilot_candidate_audit(contract, av_statements={},
                                          yahoo_statements={("SYNTHA", "cash-flow"): [source]})
    assert result["coverage_cells"].source_identity_status.eq("unverified").all()
    unmatched = result["unmatched_source_periods"]
    assert len(unmatched) == unmatched.source_row_count.sum() == 2
    assert "source_candidates_json" not in unmatched.columns and "source_value_json" not in unmatched.columns
    metadata_json = unmatched.to_json(orient="records")
    assert "987654321999999" not in metadata_json and "876543210999999" not in metadata_json
    assert set(unmatched.source_metric) == {"annualDepreciation", "annualNotAContractField"}
