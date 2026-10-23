"""Plan, resume, explicitly refresh, or replay a frozen private statement batch.

Run from the repository after installing it. Public output contains aggregate
coverage/fingerprints only. Store/ledger/receipt files remain outside GitHub.
Use a quiescent catalog: other ingestion/reader programs must not run against
the same root while collection is active.
Confirm the provider plan/usage authorization before an explicit run. The
default interval is conservative; changing it requires checking the plan and
coordinating all other consumers of the same provider credential.
"""
import argparse
import json
import os
from pathlib import Path

from systematic_alpha_lab.data_pipeline.fundamental_batch import (
    create_fundamental_batch,
    fundamental_batch_summary,
    read_fundamental_batch,
    replay_fundamental_batch,
    run_fundamental_batch,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "status", "replay"):
        command = commands.add_parser(name)
        command.add_argument("--data-root", type=Path, required=True)
        command.add_argument("--run-id", required=True)
    plan = commands.choices["plan"]
    plan.add_argument("--universe", type=Path, required=True)
    plan.add_argument("--max-total-requests", type=int, required=True)
    plan.add_argument("--max-attempts-per-job", type=int, default=1)
    plan.add_argument("--interval", type=float, default=15)
    plan.add_argument("--import-receipts", type=Path)
    plan.add_argument("--refresh-of", help="Prior run to explicitly refresh into this new run")
    plan.add_argument("--allow-proxy", action="store_true", help="Explicitly accept a frozen proxy, preserving its scope label")
    plan.add_argument("--allow-unverified-mappings", action="store_true",
                      help="Explicitly request unverified source symbols; this does not certify their identity")
    run = commands.choices["run"]
    run.add_argument("--max-requests", type=int, required=True, help="Additional attempts allowed in this invocation")
    run.add_argument("--retry-job", action="append", default=[], help="Explicit SYMBOL:FUNCTION failed/uncertain job")
    run.add_argument("--resume-after-halt", action="store_true")
    run.add_argument("--credentials", type=Path)
    run.add_argument("--key-slot", default="alphavantage_api_paid")
    args = parser.parse_args()
    try:
        if args.command == "replay":
            result = replay_fundamental_batch(args.data_root, run_id=args.run_id)
        elif args.command == "status":
            result = fundamental_batch_summary(read_fundamental_batch(args.data_root, run_id=args.run_id))
        elif args.command == "plan":
            from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
            from systematic_alpha_lab.data_pipeline.universe import (
                load_universe,
                provider_requests,
                public_universe_summary,
                require_universe_scope,
            )

            universe = load_universe(args.universe)
            require_universe_scope(universe, require_exact=not args.allow_proxy)
            requests = provider_requests(universe, provider="alpha_vantage",
                                         require_verified=not args.allow_unverified_mappings)
            imports = json.loads(args.import_receipts.read_bytes()) if args.import_receipts else []
            manifest = create_fundamental_batch(
                SnapshotStore(args.data_root), run_id=args.run_id,
                symbols=[item["provider_symbol"] for item in requests], universe_sha256=universe["manifest_sha256"],
                max_requests=args.max_total_requests, max_attempts_per_job=args.max_attempts_per_job,
                min_interval_seconds=args.interval, import_receipts=imports, refresh_of=args.refresh_of,
                universe_scope={"exact_index": "exact_current_index", "etf_proxy": "etf_proxy",
                                "secondary_index": "secondary_index"}[universe["source_receipt"]["kind"]],
            )
            result = fundamental_batch_summary(manifest)
            result["universe"] = public_universe_summary(universe)
        else:
            manifest = read_fundamental_batch(args.data_root, run_id=args.run_id)
            remaining = manifest["config"]["max_requests"] - sum(len(job["attempts"]) for job in manifest["jobs"])
            needs_client = args.max_requests > 0 and remaining > 0 and any(
                job["status"] == "pending" or job["job_id"] in args.retry_job for job in manifest["jobs"]
            ) and (not manifest["halt_reason"] or args.resume_after_halt)
            client = None
            if needs_client:
                # Credential loading belongs only to an explicit run action.
                from systematic_alpha_lab.data_pipeline.alpha_vantage_rest import AlphaVantageRESTClient
                from systematic_alpha_lab.data_pipeline.config_loader import load_credentials

                credential = os.environ.get("ALPHAVANTAGE_API_KEY")
                if not credential and args.credentials:
                    credential = load_credentials(args.credentials).get(args.key_slot)
                if not credential:
                    parser.error("Set ALPHAVANTAGE_API_KEY or supply --credentials; never put credentials on the command line")
                client = AlphaVantageRESTClient(credential)
            from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

            manifest = run_fundamental_batch(
                client, SnapshotStore(args.data_root), run_id=args.run_id, max_requests=args.max_requests,
                retry_jobs=args.retry_job, resume_after_halt=args.resume_after_halt,
            )
            result = fundamental_batch_summary(manifest)
    except (ValueError, KeyError, OSError, TypeError):
        parser.exit(1, "Batch input, universe mapping, integrity or bounded plan rejected; no dataset was certified.\n")
    print(json.dumps(result, indent=2))
    if result["state"] == "halted":
        parser.exit(2)


if __name__ == "__main__":
    main()
