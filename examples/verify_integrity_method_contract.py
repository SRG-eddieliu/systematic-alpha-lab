"""Offline public-fixture method check, not a provider or annual-model adapter."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, localcontext
from pathlib import Path

from systematic_alpha_lab.factor_research.beneish import (
    M_SCORE_COEFFICIENTS,
    beneish_m_score,
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    contract_path = root / "docs/integrity-research-contract-v1.json"
    fixture_path = root / "docs/fixtures/beneish-sunbeam-1997.json"
    contract = json.loads(contract_path.read_text())
    fixture = json.loads(fixture_path.read_text())
    definition = contract["beneish"]
    coefficients = {key: Decimal(value) for key, value in definition["coefficients"].items()}
    assert set(coefficients) == set(M_SCORE_COEFFICIENTS)
    assert all(float(value) == M_SCORE_COEFFICIENTS[key] for key, value in coefficients.items())
    assert len(definition["financial_fields"]) == 12
    assert sum(len(field["periods"]) for field in definition["financial_fields"]) == 22

    # Direct Decimal algebra from published amounts; no provider mapping/helper.
    def calculate(current: dict[str, Decimal], prior: dict[str, Decimal]):
        c, p = current, prior
        ratios = {
            "DSRI": (c["AR"] / c["Sales"]) / (p["AR"] / p["Sales"]),
            "GMI": ((p["Sales"] - p["COGS"]) / p["Sales"]) / ((c["Sales"] - c["COGS"]) / c["Sales"]),
            "AQI": (1 - (c["CA"] + c["PPE"]) / c["TA"]) / (1 - (p["CA"] + p["PPE"]) / p["TA"]),
            "SGI": c["Sales"] / p["Sales"],
            "DEPI": (p["Dep"] / (p["Dep"] + p["PPE"])) / (c["Dep"] / (c["Dep"] + c["PPE"])),
            "SGAI": (c["SGA"] / c["Sales"]) / (p["SGA"] / p["Sales"]),
            "TATA": (c["IBEI"] - c["CFO"]) / c["TA"],
            "LVGI": ((c["CL"] + c["LTD"]) / c["TA"]) / ((p["CL"] + p["LTD"]) / p["TA"]),
        }
        score = Decimal(definition["intercept"]) + sum(coefficients[key] * value for key, value in ratios.items())
        return ratios, score

    with localcontext() as context:
        context.prec = 50
        current = {key: Decimal(value) for key, value in fixture["current"].items()}
        prior = {key: Decimal(value) for key, value in fixture["prior"].items()}
        ratios, score = calculate(current, prior)
        ratio_errors = {key: abs(value - Decimal(fixture["published_ratios"][key])) for key, value in ratios.items()}
        assert all(error <= Decimal(fixture["published_ratio_absolute_tolerance"]) for error in ratio_errors.values())
        assert abs(score - Decimal(fixture["published_m_score"])) <= Decimal(fixture["published_score_absolute_tolerance"])
        actual = beneish_m_score(ratios)
        assert actual["calculation_ready"]
        float_error = abs(Decimal(str(actual["m_score"])) - score)
        assert float_error <= Decimal(fixture["decimal_oracle_to_existing_float_score_absolute_tolerance"])
        for scale in (Decimal(1000), Decimal("0.001")):
            scaled_ratios, scaled_score = calculate(
                {key: value * scale for key, value in current.items()},
                {key: value * scale for key, value in prior.items()},
            )
            assert all(abs(scaled_ratios[key] - value) < Decimal("1e-45") for key, value in ratios.items())
            assert abs(scaled_score - score) < Decimal("1e-45")
        equal = current | {"IBEI": current["CFO"]}
        neutral_ratios, neutral_score = calculate(equal, equal)
        assert neutral_ratios["TATA"] == 0
        assert all(value == 1 for key, value in neutral_ratios.items() if key != "TATA")
        assert neutral_score == Decimal("-2.480")

    print(json.dumps({
        "status": "passed",
        "definition_id": definition["definition_id"],
        "checked_scope": "public_fixture_arithmetic_and_contract_structure_only",
        "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "ratios": {key: str(value) for key, value in ratios.items()},
        "m_score_decimal": str(score),
        "existing_coefficient_function_m_score": actual["m_score"],
        "decimal_to_float_absolute_error": str(float_error),
        "published_display_matches": True,
        "common_scale_invariance": True,
        "neutral_case_m_score": str(neutral_score),
        "provider_data_read": False,
        "network_calls": 0,
        "adapter_source_timing_or_market_validation": False,
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
