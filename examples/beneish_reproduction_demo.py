"""Credential-free score checks; no private data or external calls."""
import json
import math

from systematic_alpha_lab.factor_research.beneish import (
    beneish_m_score,
    legacy_q07_quarterly_proxy,
)


def main():
    # Author's public Sunbeam Example p.3; displayed ratios rounded to 4 decimals.
    # https://apps.kelley.iu.edu/Beneish/Content/Examples/SunbeamExample.pdf
    ratios = {"DSRI": 1.1670, "GMI": 0.3002, "AQI": 0.9282, "SGI": 1.1870,
              "DEPI": 1.2831, "SGAI": 0.5157, "TATA": 0.1050, "LVGI": 0.7955}
    published = beneish_m_score(ratios)
    assert math.isclose(published["m_score"], -1.884035, abs_tol=1e-12)
    previous = {
        "entity_id": "synthetic", "fiscal_year": 2019, "fiscal_quarter": 4,
        "currency": "USD", "unit": "million", "receivables": 10, "sales": 100,
        "cost_of_goods_sold": 60, "current_assets": 40, "net_ppe": 50,
        "total_assets": 100, "depreciation": 5, "sga_expense": 10,
        "long_term_debt": 10, "current_liabilities": 20,
    }
    current = previous | {"fiscal_year": 2020, "fiscal_quarter": 1}
    legacy = legacy_q07_quarterly_proxy(current, previous)
    assert math.isclose(legacy["m_score"], -2.48, abs_tol=1e-12)
    invalid = legacy_q07_quarterly_proxy(current | {"sales": 0}, previous)
    assert invalid["flag"] is None and not invalid["calculation_ready"]
    print(json.dumps({"published_ratio_arithmetic": published,
                      "synthetic_legacy_proxy": legacy,
                      "invalid_input_remains_unknown": invalid}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
