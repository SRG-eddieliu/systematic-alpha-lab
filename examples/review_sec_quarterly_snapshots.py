"""Offline SEC quarterly review using explicit, pinned source capture IDs."""

import argparse
import json
from pathlib import Path

from systematic_alpha_lab.data_pipeline.sec_quarterly_review import review_sec_quarterly_snapshots
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--facts-snapshot", required=True)
    parser.add_argument("--submissions-snapshot", required=True)
    parser.add_argument("--history-snapshots", nargs="*", default=[])
    parser.add_argument("--unit", default="USD")
    parser.add_argument("--min-report-end", default="2009-01-01")
    args = parser.parse_args()
    try:
        store = SnapshotStore(args.data_root)
        records = [
            store.get(identifier)
            for identifier in [args.facts_snapshot, args.submissions_snapshot, *args.history_snapshots]
        ]
        if any(record is None for record in records):
            raise ValueError("Missing pinned source capture")
        manifest = review_sec_quarterly_snapshots(
            store,
            records[0],
            records[1],
            history_records=records[2:],
            unit=args.unit,
            min_report_end=args.min_report_end,
        )
    except (ValueError, FileNotFoundError):
        parser.exit(1, "Pinned SEC inputs, source contract or integrity rejected.\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
