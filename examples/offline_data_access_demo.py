"""Synthetic pinned data access; no network, credentials or real-company data."""
from __future__ import annotations

import json
from tempfile import TemporaryDirectory

from systematic_alpha_lab.data_pipeline import OfflineDataReader
from systematic_alpha_lab.data_pipeline.fundamental_snapshots import replay_fundamentals
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    with TemporaryDirectory() as root:
        store = SnapshotStore(root)
        request = {"function": "INCOME_STATEMENT", "symbol": "SYNTH"}
        payload = {
            "symbol": "SYNTH",
            "annualReports": [
                {"fiscalDateEnding": "2019-12-31", "reportedCurrency": "USD", "netIncome": "100"},
                {"fiscalDateEnding": "2020-12-31", "reportedCurrency": "USD", "netIncome": "125"},
            ],
            "quarterlyReports": [],
        }
        record = store.capture("alpha_vantage", request, json.dumps(payload).encode(),
                               observed_at="2021-03-01T12:00:00Z")
        manifest = replay_fundamentals(store, record)
        reader = OfflineDataReader(root)
        entries = reader.catalog(provider="alpha_vantage", request=request)
        assert len(entries) == 1 and entries[0]["snapshot_id"] == record["id"]
        result = reader.read(snapshot_id=record["id"], normalizer=manifest["normalizer"], table="annual",
                             start="2020-01-01", end="2020-12-31", fields=["period_end", "netIncome"])
        assert result.frame.netIncome.tolist() == ["125"]
        assert result.metadata["readiness"]["status"] == "not_certified"
        empty = reader.read(snapshot_id=record["id"], normalizer=manifest["normalizer"], table="annual",
                            start="2022-01-01")
        assert empty.frame.empty
        print(json.dumps({"source": "synthetic", "source_rows": result.metadata["source_rows"],
                          "returned_rows": result.metadata["returned_rows"],
                          "net_income_text": result.frame.netIncome.tolist(),
                          "readiness": result.metadata["readiness"]["status"],
                          "empty_range_rows": len(empty.frame)}, indent=2))


if __name__ == "__main__":
    main()
