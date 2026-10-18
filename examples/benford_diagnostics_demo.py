"""Offline significant-digit and publication-time examples on synthetic fields."""
import json

import pandas as pd

from systematic_alpha_lab.factor_research.factors.benford import (
    benford_asof_diagnostics, benford_snapshot_diagnostics,
)


def main():
    statements = pd.DataFrame({
        "asset": "synthetic-company", "period_end": "2020-03-31",
        "field": ["revenue", "net_income", "assets", "inventory"],
        "value": ["0.034", "-1200", "5e6", "7.89"],
    })
    snapshot = benford_snapshot_diagnostics(statements)
    filings = statements.assign(available_at="2020-05-01T21:00Z", currency="USD", unit="millions")
    decisions = pd.DataFrame({"asset": ["synthetic-company"] * 2,
                              "decision_at": ["2020-05-01T20:59Z", "2020-05-01T21:00Z"]})
    available = benford_asof_diagnostics(filings, decisions, fields=statements.field.tolist())
    print(json.dumps({
        "input": "explicitly synthetic", "valid_nonzero_amounts": int(snapshot.n_nonzero.iloc[0]),
        "first_digit_discrepancy": float(snapshot.chi2_d1.iloc[0]),
        "second_digit_discrepancy": float(snapshot.chi2_d2.iloc[0]),
        "cell_count_screen_d1": bool(snapshot.cell_count_screen_d1.iloc[0]),
        "score_missing_before_release": bool(pd.isna(available.chi2_d1.iloc[0])),
        "score_present_at_release": bool(pd.notna(available.chi2_d1.iloc[1])),
        "snapshot_status": snapshot.timing_status.iloc[0],
        "asof_status": available.timing_status.iloc[1],
    }, indent=2))


if __name__ == "__main__":
    main()
