"""Strict annual raw-ratio Beneish arithmetic on caller-declared canonical data.

Passing these checks establishes consistency of supplied declarations, not the
authenticity or accounting semantics of an external source. The caller selects
unique statement versions before calling this pair API; it cannot detect other
rows, duplicate filings, or source conflicts elsewhere in a panel.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from numbers import Real
from typing import Any

from systematic_alpha_lab.factor_research.beneish import M_SCORE_COEFFICIENTS, beneish_m_score

DEFINITION_ID = "beneish_2013_cashflow_annual_raw_v1"
REFERENCE_THRESHOLD = -1.78
POSITIVE_FIELDS = (
    "trade_receivables_net", "current_assets", "current_liabilities", "total_assets",
    "net_ppe", "sales", "cost_of_goods_sold", "depreciation", "sga_expense",
)
REQUIRED_FIELDS_PREVIOUS = POSITIVE_FIELDS + ("long_term_debt_noncurrent",)
REQUIRED_FIELDS_CURRENT = REQUIRED_FIELDS_PREVIOUS + (
    "income_before_extraordinary_items", "operating_cash_flow",
)


def _number(value: Any, field: str, reasons: list[str]) -> float | None:
    if value is None:
        reasons.append(f"missing:{field}")
        return None
    if (
        isinstance(value, bool)
        or getattr(getattr(value, "dtype", None), "kind", None) == "b"
        or not isinstance(value, (str, Real, Decimal))
    ):
        reasons.append(f"invalid_numeric:{field}")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        reasons.append(f"invalid_numeric:{field}")
        return None
    if not math.isfinite(number):
        reasons.append(f"nonfinite:{field}")
        return None
    # Signed inputs also need this guard: a nonzero Decimal/string must not be
    # silently converted into an apparently valid zero accrual amount.
    if number == 0:
        try:
            original_nonzero = Decimal(value) != 0 if isinstance(value, str) else value != 0
        except InvalidOperation:
            reasons.append(f"invalid_numeric:{field}")
            return None
        if original_nonzero:
            reasons.append(f"underflow_numeric:{field}")
            return None
    return number


def _text(record: Mapping[str, Any], field: str, label: str, reasons: list[str]) -> str | None:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        reasons.append(f"missing_or_invalid_metadata:{label}.{field}")
        return None
    return value.strip()


def _date(record: Mapping[str, Any], field: str, label: str, reasons: list[str]) -> date | None:
    value = record.get(field)
    if value is None:
        reasons.append(f"missing:{label}.{field}")
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        reasons.append(f"invalid_date:{label}.{field}")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        reasons.append(f"invalid_date:{label}.{field}")
        return None


def _metadata(current: Mapping[str, Any], previous: Mapping[str, Any], reasons: list[str]) -> None:
    for field in ("entity_id", "currency", "reporting_scope", "accounting_basis"):
        a = _text(current, field, "current", reasons)
        b = _text(previous, field, "previous", reasons)
        if a is not None and b is not None and a != b:
            reasons.append(f"metadata_mismatch:{field}")
    scales: list[Decimal | None] = []
    years: list[int | None] = []
    windows: list[tuple[date | None, date | None]] = []
    for label, record in (("current", current), ("previous", previous)):
        scale = _number(record.get("unit_scale"), f"{label}.unit_scale", reasons)
        exact_scale = None
        if scale is not None:
            if scale <= 0:
                reasons.append(f"nonpositive:{label}.unit_scale")
            else:
                try:
                    exact_scale = Decimal(str(record["unit_scale"]))
                except InvalidOperation:
                    reasons.append(f"invalid_numeric:{label}.unit_scale")
        scales.append(exact_scale)
        for field in ("period_type", "flow_basis"):
            if _text(record, field, label, reasons) != "annual":
                reasons.append(f"not_annual:{label}.{field}")
        year = _number(record.get("fiscal_year"), f"{label}.fiscal_year", reasons)
        if year is not None:
            try:
                exact_year = Decimal(str(record["fiscal_year"]))
                if exact_year != exact_year.to_integral_value() or not 1 <= exact_year <= 9999:
                    raise InvalidOperation
                year = int(exact_year)
            except InvalidOperation:
                reasons.append(f"invalid_fiscal_year:{label}")
                year = None
        years.append(None if year is None else int(year))
        start = _date(record, "period_start", label, reasons)
        end = _date(record, "period_end", label, reasons)
        windows.append((start, end))
        if start is not None and end is not None and not 330 <= (end - start).days + 1 <= 400:
            reasons.append(f"invalid_annual_duration:{label}")
    if all(scale is not None for scale in scales) and scales[0] != scales[1]:
        reasons.append("metadata_mismatch:unit_scale")
    if all(year is not None for year in years) and years[0] != years[1] + 1:
        reasons.append("nonconsecutive_fiscal_years")
    (current_start, current_end), (_, previous_end) = windows
    if current_end is not None and previous_end is not None and not 330 <= (current_end - previous_end).days <= 400:
        reasons.append("invalid_annual_end_spacing")
    if current_start is not None and previous_end is not None and (current_start - previous_end).days != 1:
        reasons.append("noncontiguous_annual_windows")


def annual_beneish(
    current: Mapping[str, Any], previous: Mapping[str, Any] | None, *, reference_screen: bool = False,
) -> dict[str, Any]:
    """Compute the v1 annual score from 22 required, explicitly verified amounts.

    Canonical fields are flat and listed in REQUIRED_FIELDS_CURRENT/PREVIOUS.
    Every required field needs ``field_statuses[name] == 'verified_exact'``.
    This is the caller's named semantic assertion, never external certification.
    Prior income/CFO and extra fields are ignored. Amounts accept finite real
    scalars or decimal strings, rejecting booleans and float under/overflow.

    Both records require entity_id, integer fiscal_year, period_type/flow_basis
    'annual', period_start/end as YYYY-MM-DD, currency, positive unit_scale,
    reporting_scope and accounting_basis. Annual windows count both endpoints,
    last 330--400 days and are adjacent without a gap or overlap; fiscal years
    are adjacent and period-end spacing is 330--400 days. Pair scales must be
    equal; callers perform any documented conversion before calling.

    The conservative positive-input, positive-margin/residual-share domain is
    the frozen research policy. Missing/invalid inputs produce null score/flag
    with reasons, without imputation, clipping, probability or timing inference.
    Only a literal True enables the historical M > -1.78 reference screen.
    Unique version selection and source-panel duplicate checks belong upstream.
    """
    reasons: list[str] = []
    ratios: dict[str, float | None] = dict.fromkeys(M_SCORE_COEFFICIENTS)
    result: dict[str, Any] = {
        "definition_id": DEFINITION_ID, "ratios": ratios, "m_score": None, "flag": None,
        "calculation_ready": False, "standard_definition_satisfied": False,
        "standard_definition_scope": "supplied_declarations_only",
        "source_status": "not_certified_by_calculator", "timing_status": "not_assessed",
        "research_ready": False, "reasons": reasons,
        "reference_screen": {"enabled": reference_screen is True, "operator": ">",
                             "threshold": REFERENCE_THRESHOLD,
                             "meaning": "historical_reference_only_not_fraud_ground_truth"},
    }
    if type(reference_screen) is not bool:
        reasons.append("invalid_argument:reference_screen")
    if not isinstance(current, Mapping):
        reasons.append("invalid_mapping:current")
    if not isinstance(previous, Mapping):
        reasons.append("missing_or_invalid_previous_annual")
    if reasons:
        return result
    _metadata(current, previous, reasons)
    values: dict[str, dict[str, float | None]] = {}
    for label, record, fields in (
        ("current", current, REQUIRED_FIELDS_CURRENT), ("previous", previous, REQUIRED_FIELDS_PREVIOUS),
    ):
        statuses = record.get("field_statuses")
        if not isinstance(statuses, Mapping):
            reasons.append(f"missing_or_invalid_field_statuses:{label}")
            statuses = {}
        values[label] = {}
        for field in fields:
            status = statuses.get(field)
            if not isinstance(status, str) or status != "verified_exact":
                reasons.append(f"unverified_field:{label}.{field}")
            value = _number(record.get(field), f"{label}.{field}", reasons)
            values[label][field] = value
            if value is not None and field in POSITIVE_FIELDS and value <= 0:
                reasons.append(f"nonpositive:{label}.{field}")
            if value is not None and field == "long_term_debt_noncurrent" and value < 0:
                reasons.append(f"negative:{label}.{field}")
    if reasons:
        return result
    c, p = values["current"], values["previous"]
    # Decimal monetary boundaries must not become positive through float sum
    # rounding (e.g. .1 + .7 < .8 in binary arithmetic). Fraction preserves
    # every supplied decimal digit without a context precision or epsilon.
    for label, record in (("current", current), ("previous", previous)):
        try:
            exact = {name: Fraction(str(record[name])) for name in (
                "sales", "cost_of_goods_sold", "current_assets", "net_ppe", "total_assets",
            )}
        except (ValueError, ZeroDivisionError, OverflowError):
            reasons.append(f"invalid_exact_domain_amount:{label}")
            continue
        if exact["sales"] <= exact["cost_of_goods_sold"]:
            reasons.append(f"nonpositive:{label}.gross_margin")
        if exact["current_assets"] + exact["net_ppe"] >= exact["total_assets"]:
            reasons.append(f"nonpositive:{label}.residual_asset_share")

    def finite(value: float, name: str) -> float | None:
        if not math.isfinite(value):
            reasons.append(f"nonfinite_intermediate:{name}")
            return None
        return value

    def divide(numerator: float | None, denominator: float | None, name: str) -> float | None:
        if numerator is None or denominator is None:
            return None
        if denominator == 0:
            reasons.append(f"zero_denominator:{name}")
            return None
        value = finite(numerator / denominator, name)
        if value == 0 and numerator != 0:
            reasons.append(f"underflow_intermediate:{name}")
            return None
        return value

    margins: dict[str, float | None] = {}
    residuals: dict[str, float | None] = {}
    for label, row in (("current", c), ("previous", p)):
        margin = divide(finite(row["sales"] - row["cost_of_goods_sold"], f"{label}.gross_profit"),
                        row["sales"], f"{label}.gross_margin")
        margins[label] = margin
        fraction = divide(finite(row["current_assets"] + row["net_ppe"], f"{label}.asset_sum"),
                          row["total_assets"], f"{label}.asset_fraction")
        residual = None if fraction is None else finite(1.0 - fraction, f"{label}.residual_asset_share")
        residuals[label] = residual
        for name, value in (("gross_margin", margin), ("residual_asset_share", residual)):
            if value is not None and value <= 0:
                reasons.append(f"nonpositive:{label}.{name}")
    if reasons:
        result["reasons"] = list(dict.fromkeys(reasons))
        return result

    def relative(field: str, scale: str, name: str) -> float | None:
        return divide(divide(c[field], c[scale], f"current.{name}"),
                      divide(p[field], p[scale], f"previous.{name}"), name)

    ratios["DSRI"] = relative("trade_receivables_net", "sales", "DSRI")
    ratios["GMI"] = divide(margins["previous"], margins["current"], "GMI")
    ratios["AQI"] = divide(residuals["current"], residuals["previous"], "AQI")
    ratios["SGI"] = divide(c["sales"], p["sales"], "SGI")
    ratios["DEPI"] = divide(
        divide(p["depreciation"], finite(p["depreciation"] + p["net_ppe"], "previous.depreciable_base"),
               "previous.depreciation_rate"),
        divide(c["depreciation"], finite(c["depreciation"] + c["net_ppe"], "current.depreciable_base"),
               "current.depreciation_rate"), "DEPI",
    )
    ratios["SGAI"] = relative("sga_expense", "sales", "SGAI")
    ratios["TATA"] = divide(
        finite(c["income_before_extraordinary_items"] - c["operating_cash_flow"], "current.accruals"),
        c["total_assets"], "TATA",
    )
    ratios["LVGI"] = divide(
        divide(finite(c["current_liabilities"] + c["long_term_debt_noncurrent"], "current.leverage_sum"),
               c["total_assets"], "current.leverage"),
        divide(finite(p["current_liabilities"] + p["long_term_debt_noncurrent"], "previous.leverage_sum"),
               p["total_assets"], "previous.leverage"), "LVGI",
    )
    if reasons:
        return result
    calculated = beneish_m_score(ratios)
    result.update(m_score=calculated["m_score"], calculation_ready=calculated["calculation_ready"],
                  standard_definition_satisfied=calculated["calculation_ready"], reasons=calculated["reasons"])
    if result["calculation_ready"] and reference_screen:
        result["flag"] = result["m_score"] > REFERENCE_THRESHOLD
    return result
