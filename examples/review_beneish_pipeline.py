"""Read closed, explicitly pinned AV annual snapshots; never collect or refresh."""
import argparse
import json
from pathlib import Path

from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.factor_research.beneish_pipeline import review_annual_beneish_snapshots


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate selection/context key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite selection/context value")

    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=invalid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True, help="Existing closed SnapshotStore root")
    parser.add_argument("--selection", type=Path, required=True, help="JSON: symbol -> function -> snapshot_id")
    parser.add_argument("--contexts", type=Path, help="Optional separately reviewed symbol -> context declarations")
    args = parser.parse_args()
    try:
        selection = read_json(args.selection)
        contexts = {} if args.contexts is None else read_json(args.contexts)
        if not isinstance(selection, dict) or not selection or not isinstance(contexts, dict) or set(contexts) - set(selection):
            raise ValueError("Invalid explicit selection/context")
        reader = OfflineDataReader(args.data_root)
        results = {symbol: review_annual_beneish_snapshots(reader, symbol=symbol, snapshot_ids=pins, context=contexts.get(symbol))
                   for symbol, pins in sorted(selection.items())}
    except (ValueError, TypeError, KeyError, OSError):
        parser.exit(1, "Pinned selection, context or source integrity rejected; inspect private inputs.\n")
    ready = sum(result["calculation_ready_count"] for result in results.values())
    print(json.dumps({"status": "reviewed_with_input_gaps" if any(result["calculation_ready_count"] == 0 for result in results.values()) else "snapshot_arithmetic_only",
                      "symbol_count": len(results), "calculation_ready_count": ready,
                      "network_calls": 0, "research_ready": False, "companies": results}, indent=2, allow_nan=False))
    return 0 if all(result["calculation_ready_count"] > 0 for result in results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
