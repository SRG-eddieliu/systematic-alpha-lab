"""Credential-free synthetic capture and zero-network replay demonstration."""
import json
from tempfile import TemporaryDirectory

import pandas as pd

from systematic_alpha_lab.data_pipeline.fundamental_snapshots import ingest_fundamentals
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    observed = pd.Timestamp("2020-08-01T21:00Z")
    payload = {
        "symbol": "SYNTH",
        "annualReports": [{"fiscalDateEnding": "2019-12-31", "reportedCurrency": "USD", "netIncome": "400"}],
        "quarterlyReports": [{"fiscalDateEnding": "2020-02-29", "reportedCurrency": "USD", "netIncome": "100"}],
    }
    with TemporaryDirectory() as directory:
        store = SnapshotStore(directory)
        record = store.capture("alpha_vantage", {"function": "INCOME_STATEMENT", "symbol": "SYNTH"},
                               json.dumps(payload).encode(), observed_at=observed)
        receipts = ingest_fundamentals(None, store, symbols=["SYNTH"], functions=["INCOME_STATEMENT"],
                                      max_requests=0, min_interval_seconds=0, clock=lambda: observed)
        report = pd.read_parquet(store.root / receipts[0]["tables"]["quarterly"]["path"])
        print(json.dumps({"input": "explicitly synthetic", "network_requests": 0,
                          "snapshot_reused": receipts[0]["snapshot_id"] == record["id"],
                          "tables": {name: item["rows"] for name, item in receipts[0]["tables"].items()},
                          "historical_available_at_missing": bool(report.available_at.isna().all()),
                          "unit_status": report.amount_unit_status.iloc[0]}, indent=2))


if __name__ == "__main__":
    main()
