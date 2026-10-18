"""Explicit SEC CIK collection or offline replay; data root must remain private."""
import argparse
from datetime import timedelta
import json
import os
from pathlib import Path

from systematic_alpha_lab.data_pipeline.sec_snapshots import (
    SECClient, SECError, collect_sec_snapshots, replay_sec_facts, sec_request,
)
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--ciks", nargs="+", required=True)
    parser.add_argument("--max-requests", type=int, default=2)
    parser.add_argument("--cache-hours", type=float, default=24)
    parser.add_argument("--interval", type=float, default=.5)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        plan = [sec_request(kind, cik) for cik in args.ciks for kind in ("submissions", "companyfacts")]
        # Offline replay does not read contact information or construct a client.
        source = None if args.offline else SECClient(os.environ.get("SEC_USER_AGENT"), min_interval_seconds=args.interval)
        store = SnapshotStore(args.data_root)
        receipts = collect_sec_snapshots(source, store, plan=plan, max_requests=args.max_requests,
                                         cache_max_age=timedelta(hours=args.cache_hours))
        manifests = [replay_sec_facts(store, receipts[i + 1]["record"], receipts[i]["record"])
                     for i in range(0, len(receipts), 2)]
    except SECError as exc:
        parser.exit(1, f"{exc}; stopped without retry.\n")
    except (ValueError, OverflowError):
        parser.exit(1, "SEC plan, contact header, cache integrity or source contract rejected.\n")
    print(json.dumps({"observations": receipts, "datasets": manifests}, indent=2))


if __name__ == "__main__":
    main()
