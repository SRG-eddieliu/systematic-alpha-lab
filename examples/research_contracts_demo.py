"""Synthetic-only coefficient and chronological-split checks; no network or fitting."""

import hashlib
import json

import numpy as np
import pandas as pd

from systematic_alpha_lab.alpha import weight_gmv_direction, weight_mvo, weight_mvo_direction
from systematic_alpha_lab.factor_research.study_split import monthly_chronological_split


def main():
    rows = []
    for decision in pd.date_range("2020-01-01", periods=10, freq="MS", tz="UTC") + pd.Timedelta(days=20, hours=20):
        for asset in ("synthetic:A", "synthetic:B"):
            rows.append(
                {
                    "asset_id": asset,
                    "feature_available_at": decision - pd.Timedelta(days=1),
                    "decision_at": decision,
                    "holding_start_at": decision + pd.Timedelta(days=1),
                    "holding_end_at": decision + pd.Timedelta(days=35),
                    "label_available_at": decision + pd.Timedelta(days=35, hours=2),
                }
            )
    # This hashes the synthetic timing input, not a vendor dataset or trading calendar.
    digest = hashlib.sha256(pd.DataFrame(rows).to_csv(index=False).encode()).hexdigest()
    assigned, manifest = monthly_chronological_split(pd.DataFrame(rows), source_hashes={"synthetic_timing": digest})
    retained = {name: item["retained_rows"] for name, item in manifest["segments"].items()}
    assert retained == {"development": 10, "validation": 2, "test": 4}
    assert assigned.purged.sum() == 4
    cov = pd.DataFrame([[1.0, 2.0], [2.0, 9.0]], index=["A", "B"], columns=["A", "B"])
    weights = weight_gmv_direction(cov)
    assert np.allclose([weights["A"], weights["B"]], [7 / 8, 1 / 8])
    expected = {"A": 1.0, "B": 2.0}
    assert weight_mvo(expected, cov, risk_aversion=1.0) == weight_mvo(expected, cov, risk_aversion=100.0)
    assert weight_mvo(expected, cov) == weight_mvo_direction(expected, cov)
    print(
        json.dumps(
            {
                "synthetic_only": True,
                "network_calls": 0,
                "model_fitted": False,
                "retained_rows": retained,
                "purged_rows": int(assigned.purged.sum()),
                "gmv_absolute_direction": weights,
                "legacy_risk_scaling_cancels": True,
                "historical_market_study_gate_passed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
