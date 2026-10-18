"""Review three existing statement captures without credentials or network."""
import argparse
import json
from pathlib import Path

from systematic_alpha_lab.data_pipeline.fundamental_review import review_fundamental_snapshots
from systematic_alpha_lab.data_pipeline.fundamental_snapshots import FUNCTIONS
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    store = SnapshotStore(args.data_root)
    records = [store.latest("alpha_vantage", {"function": function, "symbol": args.symbol}) for function in FUNCTIONS]
    if any(record is None for record in records):
        parser.error("Collect all three statement snapshots before review")
    try:
        manifest = review_fundamental_snapshots(store, records)
    except ValueError:
        parser.exit(1, "Statement integrity, source contract or numeric amount rejected.\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
