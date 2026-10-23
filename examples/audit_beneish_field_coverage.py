"""Aggregate field coverage from a closed, explicitly pinned statement root."""
import argparse
import json
from pathlib import Path

from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.factor_research.beneish_field_audit import SUPPORTED_NORMALIZERS, audit_beneish_field_coverage
from systematic_alpha_lab.factor_research.beneish_pipeline import NORMALIZER


def load_selection(path):
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("Duplicate selection key")
            values[key] = value
        return values

    def invalid(value):
        raise ValueError("Nonfinite selection constant")

    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=invalid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True, help="Closed SnapshotStore root only")
    parser.add_argument("--selection", type=Path, required=True, help="Private list of symbol/function/snapshot_id selections")
    parser.add_argument("--normalizer", choices=SUPPORTED_NORMALIZERS, default=NORMALIZER,
                        help="Exact common normalizer pin; recovery is field-audit intake only")
    args = parser.parse_args()
    try:
        result = audit_beneish_field_coverage(OfflineDataReader(args.data_root), selections=load_selection(args.selection),
                                             normalizer=args.normalizer)
    except (ValueError, TypeError, KeyError, OSError):
        parser.exit(1, "Pinned source selection or integrity rejected; inspect private inputs.\n")
    # The audit's fixed output schema contains counts and policies only.
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
