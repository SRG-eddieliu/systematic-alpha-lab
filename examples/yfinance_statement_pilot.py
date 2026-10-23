"""Explicit, private Yahoo candidate capture or fixed-receipt offline verification."""
import argparse
import json
from pathlib import Path

from systematic_alpha_lab.data_pipeline.supplemental_pilot import collect_yfinance_pilot, verify_yfinance_pilot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--plan", type=Path, help="Private, research-approved company and fiscal-period contract")
    parser.add_argument("--code-commit", help="Exact implementation commit; required for online capture")
    parser.add_argument("--max-session-requests", type=int, default=40)
    parser.add_argument("--offline", action="store_true", help="Verify existing pins only; no yfinance import or capture")
    args = parser.parse_args()
    try:
        if args.offline:
            if args.plan is not None:
                raise ValueError("Offline verification uses the captured contract, not a replacement plan")
            result = verify_yfinance_pilot(args.data_root)
        else:
            if args.plan is None:
                raise ValueError("An explicit research contract is required before collection")
            receipt = collect_yfinance_pilot(
                args.data_root, plan=json.loads(args.plan.read_bytes()), code_commit=args.code_commit,
                max_session_requests=args.max_session_requests,
            )
            result = {"collection": receipt["collection"], "candidate_only": True,
                      "accepted_research_fields": 0, "verification": verify_yfinance_pilot(args.data_root)}
    except (ValueError, KeyError, TypeError, OSError, ImportError):
        parser.exit(1, "Pilot plan, runtime, source schema or pinned integrity rejected; inspect private evidence.\n")
    print(json.dumps(result, indent=2))
    if not args.offline and result["collection"]["stopped"]:
        parser.exit(1, "Collection stopped within its bound; partial captures retained without retry.\n")


if __name__ == "__main__":
    main()
