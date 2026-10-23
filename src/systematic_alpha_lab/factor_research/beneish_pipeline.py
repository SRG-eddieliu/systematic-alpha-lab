"""Pinned annual AV inputs for the Beneish calculator, with explicit gaps.

No collection, normalization, source certification or historical as-of selection.
The caller must use a closed catalog. Context declarations bind to exact input
snapshots; they are never inferred from provider dates, symbols or amount names.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping

import pandas as pd

from .beneish_standard import annual_beneish

NORMALIZER = "av_fundamentals_v1"
FUNCTIONS = ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW")
AV_CANDIDATES = {
    "trade_receivables_net": ("BALANCE_SHEET", "currentNetReceivables"),
    "current_assets": ("BALANCE_SHEET", "totalCurrentAssets"),
    "current_liabilities": ("BALANCE_SHEET", "totalCurrentLiabilities"),
    "total_assets": ("BALANCE_SHEET", "totalAssets"),
    "net_ppe": ("BALANCE_SHEET", "propertyPlantEquipment"),
    "long_term_debt_noncurrent": ("BALANCE_SHEET", "longTermDebtNoncurrent"),
    "sales": ("INCOME_STATEMENT", "totalRevenue"),
    "cost_of_goods_sold": ("INCOME_STATEMENT", "costofGoodsAndServicesSold"),
    "depreciation": ("INCOME_STATEMENT", "depreciation"),
    "sga_expense": ("INCOME_STATEMENT", "sellingGeneralAndAdministrative"),
    "income_before_extraordinary_items": ("INCOME_STATEMENT", "incomeBeforeExtraordinaryItems"),
    "operating_cash_flow": ("CASH_FLOW", "operatingCashflow"),
}
CONTEXT_FIELDS = (
    "entity_id", "fiscal_year", "period_start", "unit_scale", "reporting_scope",
    "accounting_basis", "flow_basis",
)


def review_annual_beneish_snapshots(reader, *, symbol, snapshot_ids, context=None):
    """Read exactly three pinned annual tables and return JSON-safe diagnostics.

    Without a separately reviewed context, dates/units/identity and field
    semantics remain unverified and scores remain null. An optional context has
    ``selection`` equal to snapshot_ids, ``periods`` keyed by YYYY-MM-DD with
    explicit CONTEXT_FIELDS and nonempty metadata_evidence, and ``field_mappings``
    with status/evidence for each canonical name. Only IBEI permits an explicitly
    named ``income_field`` bridge; all other source candidates stay fixed.

    Supplied declarations do not authenticate a provider or clear research gates.
    Source/date/version ambiguity rejects the selection, not a fabricated score.
    No input frames, context, catalog or source files are modified.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("An explicit provider symbol is required")
    if not isinstance(snapshot_ids, Mapping) or set(snapshot_ids) != set(FUNCTIONS):
        raise ValueError("Pin exactly the three statement snapshot IDs")
    if context is not None and (
        not isinstance(context, Mapping) or context.get("selection") != dict(snapshot_ids)
        or not isinstance(context.get("periods"), Mapping)
        or not isinstance(context.get("field_mappings"), Mapping)
    ):
        raise ValueError("Reviewed context must bind to this exact source selection")
    # This also rejects non-JSON and nonfinite context metadata before use.
    context_json = json.dumps(context, sort_keys=True, allow_nan=False)
    mappings = {} if context is None else context["field_mappings"]
    if set(mappings) - set(AV_CANDIDATES):
        raise ValueError("Unknown canonical field in reviewed context")
    frames, manifests, dates = {}, {}, set()
    for function in FUNCTIONS:
        read = reader.read(snapshot_id=snapshot_ids[function], normalizer=NORMALIZER, table="annual")
        metadata = read.metadata
        if metadata.get("provider") != "alpha_vantage" or metadata.get("request") != {
            "function": function, "symbol": symbol,
        }:
            raise ValueError("Pinned source does not match the declared function/symbol")
        if any(metadata.get(key) != expected for key, expected in {
            "snapshot_id": snapshot_ids[function], "normalizer": NORMALIZER, "table": "annual",
        }.items()):
            raise ValueError("Returned source identity differs from the pinned selection")
        frame = read.frame.copy(deep=True)
        if not {"period_end", "period_type", "currency"}.issubset(frame):
            raise ValueError("Annual source lacks required date/type/currency metadata")
        if not frame.period_type.eq("annual").all():
            raise ValueError("Source is not an annual statement table")
        labels = pd.to_datetime(frame.period_end, utc=True, errors="raise")
        if labels.isna().any() or labels.duplicated().any() or not labels.eq(labels.dt.normalize()).all():
            raise ValueError("Missing, ambiguous or non-date annual period labels")
        frame["_period"] = labels.dt.strftime("%Y-%m-%d")
        frames[function] = frame.set_index("_period")
        manifests[function] = {key: metadata[key] for key in (
            "snapshot_id", "normalizer", "table", "provider", "request", "observed_at",
            "raw_sha256", "table_sha256", "manifest_sha256",
        )}
        dates.update(frame["_period"])
    if context is not None and set(context["periods"]) - dates:
        raise ValueError("Reviewed context contains periods absent from this selection")
    observations, period_issues = {}, {}
    for period in sorted(dates):
        issues, rows = [], {}
        for function, frame in frames.items():
            if period not in frame.index:
                issues.append("missing_statement:" + function)
            else:
                rows[function] = frame.loc[period]
        currencies = [rows[function]["currency"] for function in ("INCOME_STATEMENT", "BALANCE_SHEET") if function in rows]
        currency_ok = len(currencies) == 2 and all(
            isinstance(value, str) and bool(value.strip()) and value == currencies[0] for value in currencies
        )
        if not currency_ok:
            issues.append("source_currency_missing_or_mismatch")
        if "CASH_FLOW" in rows and currency_ok and rows["CASH_FLOW"]["currency"] != currencies[0]:
            issues.append("current_cash_flow_currency_mismatch")
        declared = {} if context is None else context["periods"].get(period, {})
        if not isinstance(declared, Mapping):
            raise TypeError("Period context must be an object")
        evidence = declared.get("metadata_evidence")
        context_ok = isinstance(evidence, str) and bool(evidence.strip())
        record = {key: declared.get(key) if context_ok else None for key in CONTEXT_FIELDS}
        record.update(period_end=period, period_type="annual", currency=currencies[0] if currency_ok else None)
        record["field_statuses"] = {}
        for canonical, (function, field) in AV_CANDIDATES.items():
            mapping = mappings.get(canonical, {})
            if not isinstance(mapping, Mapping):
                raise TypeError("Field mapping must be an object")
            if canonical == "income_before_extraordinary_items" and context is not None:
                field = context.get("income_field", field)
                if not isinstance(field, str) or not field.strip():
                    raise ValueError("Income bridge field must be explicit")
            row = rows.get(function)
            value = None if row is None or field not in row else row[field]
            # Recognize provider missing markers without filling any amount.
            missing = pd.isna(value) or isinstance(value, str) and value.strip() in ("", "None", "null")
            record[canonical] = None if missing else value
            mapping_evidence = mapping.get("evidence")
            record["field_statuses"][canonical] = (
                "verified_exact" if mapping.get("status") == "verified_exact"
                and isinstance(mapping_evidence, str) and mapping_evidence.strip()
                else "unverified"
            )
        observations[period], period_issues[period] = record, issues
    results, previous = [], None
    for period, current in observations.items():
        result = annual_beneish(current, previous)
        issues = list(period_issues[period])
        if previous is not None:
            # Prior CFO/IBEI are not required by the 22-amount formula.
            issues.extend("previous:" + reason for reason in period_issues[previous["period_end"]]
                          if reason not in ("missing_statement:CASH_FLOW", "current_cash_flow_currency_mismatch"))
        if issues:
            result.update(m_score=None, flag=None, calculation_ready=False, standard_definition_satisfied=False)
            result["reasons"] = sorted(set(result["reasons"] + issues))
        results.append({"period_end": period, **result})
        previous = current
    reasons = Counter(reason for result in results for reason in result["reasons"])
    return {
        "definition_id": "beneish_2013_cashflow_annual_raw_v1", "provider_symbol": symbol,
        "selection": dict(snapshot_ids), "input_manifests": manifests,
        "context_sha256": hashlib.sha256(context_json.encode()).hexdigest(),
        "rows": results, "period_count": len(results),
        "calculation_ready_count": sum(result["calculation_ready"] for result in results),
        "reason_counts": dict(sorted(reasons.items())),
        "source_status": "source_hashes_checked_semantics_not_certified",
        "timing_status": "snapshot_only_availability_unverified", "research_ready": False,
        "network_calls": 0, "implicit_refresh": False,
    }
