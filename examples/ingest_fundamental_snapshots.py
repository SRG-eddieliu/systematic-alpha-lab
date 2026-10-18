"""Bounded collection or offline replay; keep the data root outside GitHub."""
import argparse
from datetime import timedelta
import json
import logging
import os
from pathlib import Path

from systematic_alpha_lab.data_pipeline.alpha_vantage_rest import AlphaVantageError, AlphaVantageRESTClient
from systematic_alpha_lab.data_pipeline.config_loader import load_credentials
from systematic_alpha_lab.data_pipeline.fundamental_snapshots import FUNCTIONS, ingest_fundamentals
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--functions", nargs="+", choices=FUNCTIONS, default=list(FUNCTIONS))
    parser.add_argument("--max-requests", type=int, default=3)
    parser.add_argument("--cache-hours", type=float, default=24)
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--key-slot", default="alphavantage_api_paid")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    client = None
    if not args.offline:
        key = os.environ.get("ALPHAVANTAGE_API_KEY")
        if not key and args.credentials:
            key = load_credentials(args.credentials).get(args.key_slot)
        if not key:
            parser.error("Set ALPHAVANTAGE_API_KEY or supply --credentials and --key-slot; do not put a key on the command line")
        client = AlphaVantageRESTClient(key)
    try:
        result = ingest_fundamentals(
            client, SnapshotStore(args.data_root), symbols=args.symbols, functions=args.functions,
            max_requests=args.max_requests, cache_max_age=timedelta(hours=args.cache_hours),
            min_interval_seconds=args.interval,
        )
    except AlphaVantageError as exc:
        parser.exit(1, f"{exc}; stopped without retry or key rotation.\n")
    except ValueError:
        parser.exit(1, "Input plan, cache integrity or source schema rejected; no research dataset was certified.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
