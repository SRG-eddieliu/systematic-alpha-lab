"""Provider-only statement review on explicitly synthetic observations."""
import json
from tempfile import TemporaryDirectory

import pandas as pd

from systematic_alpha_lab.data_pipeline.fundamental_review import FIELDS, review_fundamental_snapshots
from systematic_alpha_lab.data_pipeline.quarterly_review import review_quarterly_snapshots
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    with TemporaryDirectory() as root:
        store, records = SnapshotStore(root), []
        for function, field in FIELDS.items():
            annual, quarterly = [], []
            for year in [2020, 2021]:
                value = 40 if function == "INCOME_STATEMENT" else 32 if function == "CASH_FLOW" else 100 + 20 * (year - 2020)
                row = {"fiscalDateEnding": f"{year}-12-31", "reportedCurrency": "USD", field: str(value)}
                if function == "CASH_FLOW": row["netIncome"] = "40"
                annual.append(row)
                for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
                    quarterly.append({**row, "fiscalDateEnding": f"{year}-{month:02d}-{day}",
                                      field: str(value if function == "BALANCE_SHEET" else value // 4)})
            payload = {"symbol": "SYNTH", "annualReports": annual, "quarterlyReports": quarterly}
            records.append(store.capture("alpha_vantage", {"function": function, "symbol": "SYNTH"}, json.dumps(payload).encode()))
        manifest = review_fundamental_snapshots(store, records)
        annual = pd.read_parquet(store.root / manifest["tables"]["annual_review"]["path"])
        quarter_manifest = review_quarterly_snapshots(store, records)
        quarters = pd.read_parquet(store.root / quarter_manifest["tables"]["quarterly_review"]["path"])
        print(json.dumps({"synthetic_only": True, "network_calls": 0, "annual_rows": len(annual),
                          "candidate_rows": int(annual.annual_accrual_candidate.notna().sum()),
                          "quarterly_rows": len(quarters), "quarterly_candidate_rows": int(quarters.calculation_ready.sum()),
                          "available_at_missing": bool(annual.available_at.isna().all())}))


if __name__ == "__main__":
    main()
