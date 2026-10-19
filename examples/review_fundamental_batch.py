"""Offline multi-company diagnostics; redirect the receipt into a private file."""
import argparse
import json
from pathlib import Path

from systematic_alpha_lab.data_pipeline.batch_review import review_fundamental_batch
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--symbols", nargs="+")
    mode.add_argument("--replay-receipt", type=Path, help="Pin the selection from an earlier JSON receipt")
    args = parser.parse_args()
    try:
        selection = None
        symbols = args.symbols
        if args.replay_receipt:
            receipt = json.loads(args.replay_receipt.read_text())
            selection = receipt["selection"]
            symbols = list(selection)
        result = review_fundamental_batch(SnapshotStore(args.data_root), symbols=symbols, snapshot_ids=selection)
    except (ValueError, KeyError, TypeError, FileNotFoundError):
        parser.exit(1, "Batch selection, receipt or integrity rejected; inspect private inputs.\n")
    print(json.dumps(result, indent=2))
    # A partial sample is explicit both in the receipt and to a calling workflow.
    return {"complete": 0, "partial": 2, "no_usable_symbols": 1}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
