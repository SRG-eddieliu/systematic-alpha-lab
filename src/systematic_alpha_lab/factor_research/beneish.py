"""Raw eight-ratio M arithmetic and an explicitly legacy quarterly proxy.

No annual/TTM adapter, winsorization, fraud probability, availability time, or
market-factor integration is supplied. The Q07 proxy deliberately preserves
its quarterly fields and incomplete balance-sheet accrual definition.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

M_SCORE_COEFFICIENTS = {
    "DSRI": 0.920, "GMI": 0.528, "AQI": 0.404, "SGI": 0.892,
    "DEPI": 0.115, "SGAI": -0.172, "TATA": 4.679, "LVGI": -0.327,
}
LEGACY_Q07_THRESHOLD = -2.22
QUARTER_FIELDS = (
    "receivables", "sales", "cost_of_goods_sold", "current_assets", "net_ppe",
    "total_assets", "depreciation", "sga_expense", "long_term_debt", "current_liabilities",
)


def _number(value: Any, field: str, reasons: list[str]) -> float | None:
    if value is None:
        reasons.append(f"missing:{field}")
        return None
    if isinstance(value, bool) or getattr(getattr(value, "dtype", None), "kind", None) == "b":
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
    return number


def beneish_m_score(ratios: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the unweighted eight-ratio linear formula, without a flag.

    Canonical uppercase ratio names are required. Missing/nonfinite inputs or
    overflowing arithmetic yield ``m_score=None`` with reasons. This arithmetic
    alone does not certify the ratios' definition, period, or original model's
    population preprocessing. Numeric values are converted to finite floats;
    booleans are rejected. Extra mapping fields are ignored.
    """
    reasons: list[str] = []
    values = {name: None for name in M_SCORE_COEFFICIENTS}
    result = {"ratios": values, "m_score": None, "calculation_ready": False, "reasons": reasons}
    if not isinstance(ratios, Mapping):
        reasons.append("invalid_mapping:ratios")
        return result
    for name in values:
        values[name] = _number(ratios.get(name), name, reasons)
    if reasons:
        return result
    terms = [-4.840] + [M_SCORE_COEFFICIENTS[name] * values[name] for name in values]
    if not all(math.isfinite(term) for term in terms):
        reasons.append("nonfinite:m_score")
        return result
    try:
        score = math.fsum(terms)
    except OverflowError:
        reasons.append("nonfinite:m_score")
        return result
    if not math.isfinite(score):
        reasons.append("nonfinite:m_score")
        return result
    result.update(m_score=score, calculation_ready=True)
    return result


def legacy_logistic_score(m_score: Any) -> float | None:
    """Return Q07's hand-set sigmoid(M + 2.22), NEVER a fraud probability.

    The exponent is clipped to [-100, 100] exactly as in Q07. Invalid/nonfinite
    scores return None rather than being clipped into an apparently valid value.
    """
    reasons: list[str] = []
    score = _number(m_score, "m_score", reasons)
    if score is None:
        return None
    exponent = max(-100.0, min(100.0, -(score - LEGACY_Q07_THRESHOLD)))
    return 1.0 / (1.0 + math.exp(exponent))


def _quarter_ordinal(record: Mapping[str, Any], label: str, reasons: list[str]) -> int | None:
    year = _number(record.get("fiscal_year"), f"{label}.fiscal_year", reasons)
    quarter = _number(record.get("fiscal_quarter"), f"{label}.fiscal_quarter", reasons)
    if year is None or quarter is None:
        return None
    if not year.is_integer() or not 1 <= year <= 9999:
        reasons.append(f"invalid_fiscal_year:{label}")
        return None
    if not quarter.is_integer() or not 1 <= quarter <= 4:
        reasons.append(f"invalid_fiscal_quarter:{label}")
        return None
    return int(year) * 4 + int(quarter)


def legacy_q07_quarterly_proxy(
    current: Mapping[str, Any], previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Reproduce Q07 arithmetic on a caller-selected, consecutive entity pair.

    Both records need a nonempty stable ``entity_id``, fiscal_year,
    fiscal_quarter, and QUARTER_FIELDS. These are direct quarterly flows and
    period-end stocks, not YTD or annual/TTM inputs. The caller must resolve
    duplicate source versions before selecting a pair; this pair API cannot
    detect duplicate rows elsewhere. Neither source rows nor inputs are mutated.

    Unlike the notebook, missing/nonfinite data, zero denominators, a quarter
    gap or identity mismatch yield no score/flag. Missing currency/unit permits
    arithmetic with explicit context warnings; declared mismatches reject the
    pair. Declared consistency never establishes source certification.

    TATA remains (change in current assets - change in current liabilities) /
    current total assets. The original -2.22 flag and logistic score are legacy
    conventions, not the standard Beneish cutoff or calibrated probability.
    """
    reasons: list[str] = []
    warnings: list[str] = []
    ratios: dict[str, float | None] = {name: None for name in M_SCORE_COEFFICIENTS}
    result: dict[str, Any] = {
        "definition": "legacy_q07_quarterly_proxy_v1", "ratios": ratios,
        "m_score": None, "flag": None, "threshold": LEGACY_Q07_THRESHOLD,
        "legacy_logistic_score": None, "calculation_ready": False,
        "reasons": reasons, "context_warnings": warnings,
        "metadata_status": "unverified", "source_status": "not_certified",
        "timing_status": "snapshot_only_availability_unverified",
    }
    if not isinstance(current, Mapping):
        reasons.append("invalid_mapping:current")
    if not isinstance(previous, Mapping):
        reasons.append("missing_or_invalid_previous_quarter")
    if reasons:
        return result
    identities = []
    for label, record in (("current", current), ("previous", previous)):
        identity = record.get("entity_id")
        if not isinstance(identity, str) or not identity.strip():
            reasons.append(f"missing_or_invalid_entity_id:{label}")
        identities.append(identity)
    if not reasons and identities[0] != identities[1]:
        reasons.append("entity_mismatch")
    current_q = _quarter_ordinal(current, "current", reasons)
    previous_q = _quarter_ordinal(previous, "previous", reasons)
    if current_q is not None and previous_q is not None and current_q != previous_q + 1:
        reasons.append("nonconsecutive_fiscal_quarters")
    metadata_complete = True
    for field in ("currency", "unit"):
        a, b = current.get(field), previous.get(field)
        a_valid = isinstance(a, str) and bool(a.strip())
        b_valid = isinstance(b, str) and bool(b.strip())
        if not (a_valid and b_valid):
            metadata_complete = False
            warnings.append(f"missing_or_invalid_metadata:{field}")
        elif a.strip() != b.strip():
            reasons.append(f"metadata_mismatch:{field}")
            metadata_complete = False
    if metadata_complete:
        result["metadata_status"] = "caller_declared_consistent"
    if reasons:
        return result
    values = {
        label: {field: _number(record.get(field), f"{label}.{field}", reasons) for field in QUARTER_FIELDS}
        for label, record in (("current", current), ("previous", previous))
    }
    if reasons:
        return result
    c, p = values["current"], values["previous"]

    def finite(value: float, label: str) -> float | None:
        if not math.isfinite(value):
            reasons.append(f"nonfinite_intermediate:{label}")
            return None
        return value

    def divide(numerator: float | None, denominator: float | None, label: str) -> float | None:
        if numerator is None or denominator is None:
            return None
        if denominator == 0:
            reasons.append(f"zero_denominator:{label}")
            return None
        return finite(numerator / denominator, label)

    def pair_ratio(field: str, scale: str, label: str) -> float | None:
        return divide(divide(c[field], c[scale], label), divide(p[field], p[scale], label), label)

    ratios["DSRI"] = pair_ratio("receivables", "sales", "DSRI")
    ratios["GMI"] = divide(
        divide(finite(p["sales"] - p["cost_of_goods_sold"], "GMI"), p["sales"], "GMI"),
        divide(finite(c["sales"] - c["cost_of_goods_sold"], "GMI"), c["sales"], "GMI"), "GMI",
    )
    current_asset_fraction = divide(finite(c["current_assets"] + c["net_ppe"], "AQI"), c["total_assets"], "AQI")
    prior_asset_fraction = divide(finite(p["current_assets"] + p["net_ppe"], "AQI"), p["total_assets"], "AQI")
    ratios["AQI"] = divide(
        None if current_asset_fraction is None else 1.0 - current_asset_fraction,
        None if prior_asset_fraction is None else 1.0 - prior_asset_fraction, "AQI",
    )
    ratios["SGI"] = divide(c["sales"], p["sales"], "SGI")
    ratios["DEPI"] = divide(
        divide(p["depreciation"], finite(p["depreciation"] + p["net_ppe"], "DEPI"), "DEPI"),
        divide(c["depreciation"], finite(c["depreciation"] + c["net_ppe"], "DEPI"), "DEPI"), "DEPI",
    )
    ratios["SGAI"] = pair_ratio("sga_expense", "sales", "SGAI")
    ratios["LVGI"] = divide(
        divide(finite(c["long_term_debt"] + c["current_liabilities"], "LVGI"), c["total_assets"], "LVGI"),
        divide(finite(p["long_term_debt"] + p["current_liabilities"], "LVGI"), p["total_assets"], "LVGI"), "LVGI",
    )
    ca_change = finite(c["current_assets"] - p["current_assets"], "TATA")
    cl_change = finite(c["current_liabilities"] - p["current_liabilities"], "TATA")
    change = None if ca_change is None or cl_change is None else finite(ca_change - cl_change, "TATA")
    ratios["TATA"] = divide(change, c["total_assets"], "TATA")
    if reasons:
        result["reasons"] = list(dict.fromkeys(reasons))
        return result
    calculated = beneish_m_score(ratios)
    result.update(m_score=calculated["m_score"], calculation_ready=calculated["calculation_ready"])
    result["reasons"] = calculated["reasons"]
    if result["calculation_ready"]:
        score = result["m_score"]
        result.update(flag=score > LEGACY_Q07_THRESHOLD, legacy_logistic_score=legacy_logistic_score(score))
    return result
