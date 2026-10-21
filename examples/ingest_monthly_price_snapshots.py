"""Collect bounded monthly prices or replay exact captures without credentials."""

import argparse
import json
import os
from datetime import timedelta
from pathlib import Path

from systematic_alpha_lab.data_pipeline.alpha_vantage_rest import AlphaVantageError, AlphaVantageRESTClient
from systematic_alpha_lab.data_pipeline.config_loader import load_credentials
from systematic_alpha_lab.data_pipeline.monthly_price_snapshots import ingest_monthly_prices, replay_monthly_prices
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--symbols", nargs="+")
    source.add_argument("--snapshot-ids", nargs="+")
    parser.add_argument(
        "--public-demo", action="store_true", help="Separate official IBM example; uses no user credential"
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--max-requests", type=int, default=3)
    parser.add_argument("--cache-hours", type=float, default=24)
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--key-slot", default="alphavantage_api")
    args = parser.parse_args()
    if args.snapshot_ids and (args.public_demo or args.credentials):
        parser.error("Exact snapshot replay uses the stored source mode and no credentials")
    if args.public_demo and args.credentials:
        parser.error("Public demo does not use a private credential file")
    try:
        store = SnapshotStore(args.data_root)
        if args.snapshot_ids:
            records = [store.get(identifier) for identifier in args.snapshot_ids]
            if any(record is None for record in records):
                raise ValueError("Missing pinned price capture")
            result = [replay_monthly_prices(store, record) for record in records]
        else:
            client = None
            if not args.offline:
                if args.public_demo:
                    credential = "demo"
                else:
                    credential = os.environ.get("ALPHAVANTAGE_API_KEY") or os.environ.get("ALPHA_VANTAGE_API_KEY")
                    if not credential and args.credentials:
                        credential = load_credentials(args.credentials).get(args.key_slot)
                    if not credential:
                        parser.error(
                            "Set ALPHAVANTAGE_API_KEY or supply --credentials/--key-slot; keep credentials off command lines"
                        )
                client = AlphaVantageRESTClient(credential)
            result = ingest_monthly_prices(
                client,
                store,
                symbols=args.symbols,
                access_mode="public_demo" if args.public_demo else "user",
                max_requests=args.max_requests,
                cache_max_age=timedelta(hours=args.cache_hours),
                min_interval_seconds=args.interval,
            )
    except AlphaVantageError as error:
        parser.exit(1, f"{error}; stopped without retry or source-mode fallback.\n")
    except (ValueError, OSError):
        parser.exit(1, "Price inputs, integrity or source contract rejected.\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
