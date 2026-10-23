"""Freeze explicit private universe inputs; stdout contains aggregate evidence only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from systematic_alpha_lab.data_pipeline.universe import (
    freeze_universe,
    public_universe_summary,
    require_universe_scope,
    write_universe,
)


def _read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate universe input JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite universe input JSON constant")

    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=invalid_constant)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records-json", required=True)
    parser.add_argument("--source-receipt-json", required=True)
    parser.add_argument("--output", required=True, help="New immutable manifest in a private data root")
    parser.add_argument("--index-name", default="S&P 500")
    parser.add_argument("--require-exact", action="store_true")
    args = parser.parse_args(argv)
    manifest = freeze_universe(_read(args.records_json), _read(args.source_receipt_json), index_name=args.index_name)
    require_universe_scope(manifest, require_exact=args.require_exact)
    write_universe(manifest, args.output)
    print(json.dumps(public_universe_summary(manifest), sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
