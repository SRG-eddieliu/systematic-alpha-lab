"""Fully synthetic SEC-shaped observations; no network or contact information."""
import json
from tempfile import TemporaryDirectory

import pandas as pd

from systematic_alpha_lab.data_pipeline.sec_snapshots import (
    collect_sec_snapshots, replay_sec_facts, sec_request, select_sec_context,
)
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    cik, accession = "0000000042", "0000000042-20-000001"
    submissions = {"cik": cik, "filings": {"recent": {
        "accessionNumber": [accession], "form": ["10-Q"], "filingDate": ["2020-07-30"],
        "reportDate": ["2020-06-30"], "acceptanceDateTime": ["2020-07-30T21:00:00Z"],
    }, "files": []}}
    base = {"accn": accession, "form": "10-Q", "filed": "2020-07-30", "fy": 2020,
            "fp": "Q2", "end": "2020-06-30"}
    facts = {"cik": 42, "entityName": "Explicitly Synthetic Entity", "facts": {"us-gaap": {
        "Assets": {"units": {"USD": [{**base, "val": 1000}]}},
        "NetIncomeLoss": {"units": {"USD": [{**base, "start": "2020-04-01", "val": 30}]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {
            "USD": [{**base, "start": "2020-01-01", "val": 60}],
        }},
    }}}
    plan = [sec_request(kind, cik) for kind in ("submissions", "companyfacts")]
    with TemporaryDirectory() as root:
        store = SnapshotStore(root)
        records = [store.capture("sec", request, json.dumps(payload).encode())
                   for request, payload in zip(plan, [submissions, facts])]
        cached = collect_sec_snapshots(None, store, plan=plan, max_requests=0)
        manifest = replay_sec_facts(store, records[1], records[0])
        frame = pd.read_parquet(store.root / manifest["tables"]["facts"]["path"])
        cfo = select_sec_context(frame, accession=accession, namespace="us-gaap",
                                 tag="NetCashProvidedByUsedInOperatingActivities", unit="USD",
                                 period_start="2020-01-01", period_end="2020-06-30")
        print(json.dumps({"synthetic_only": True, "network_calls": 0, "cache_hits": sum(
            row["cache_hit"] for row in cached), "facts": len(frame),
            "cash_flow_duration_days": int(cfo.duration_days),
            "available_at_missing": bool(frame.available_at.isna().all())}))


if __name__ == "__main__":
    main()
