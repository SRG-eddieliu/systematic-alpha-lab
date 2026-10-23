"""Author amounts with explicitly synthetic annual metadata; no provider data."""
import json
from pathlib import Path

from systematic_alpha_lab.factor_research.beneish_standard import annual_beneish


def main():
    docs = Path(__file__).resolve().parents[1] / "docs"
    fixture = json.loads((docs / "fixtures/beneish-sunbeam-1997.json").read_text())
    contract = json.loads((docs / "integrity-research-contract-v1.json").read_text())["beneish"]

    def observation(label, year):
        # These dates/scope/scale are synthetic API-test declarations, not
        # recovered Sunbeam filing metadata or authentic availability evidence.
        row = {field["name"]: fixture[label][field["symbol"]] for field in contract["financial_fields"]}
        return row | {
            "entity_id": "public-example-synthetic-context", "fiscal_year": year,
            "period_type": "annual", "flow_basis": "annual", "period_start": f"{year}-01-01",
            "period_end": f"{year}-12-31", "currency": "USD", "unit_scale": 1,
            "reporting_scope": "synthetic_example", "accounting_basis": "synthetic_example",
            "field_statuses": {field["name"]: "verified_exact" for field in contract["financial_fields"]},
        }

    current, previous = observation("current", 1997), observation("prior", 1996)
    result = annual_beneish(current, previous)
    assert result["calculation_ready"]
    assert abs(result["m_score"] - (-1.8841840767415743)) < 1e-12
    assert result["flag"] is None and result["research_ready"] is False
    incomplete = annual_beneish(current | {"depreciation": None}, previous)
    assert incomplete["m_score"] is None and incomplete["flag"] is None
    assert incomplete["calculation_ready"] is False
    print(json.dumps({"context": "synthetic_metadata_public_author_amounts_only",
                      "public_example": result, "missing_depreciation": incomplete}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
