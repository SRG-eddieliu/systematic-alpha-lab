"""Read-only key audit for a privately supplied financial-statement CSV.

Prints aggregate evidence only. Does not deduplicate, repair or redistribute rows.
"""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def audit_period_keys(frame: pd.DataFrame, income_field: str) -> dict:
    required = {"gvkey", "fyearq", "fqtr", "datadate", income_field, "oancfy", "atq"}
    if not required.issubset(frame):
        raise ValueError(f"Missing input fields: {sorted(required - set(frame))}")
    data = frame.copy()
    identity = data.gvkey.astype("string").str.strip().replace("", pd.NA)
    spaces = int((identity.ne(data.gvkey.astype("string"))).fillna(False).sum())
    data["gvkey"] = identity
    data["datadate"] = pd.to_datetime(data.datadate, utc=True, errors="raise")
    for column in ("fyearq", "fqtr"):
        data[column] = pd.to_numeric(data[column], errors="raise")
    keys = ["gvkey", "fyearq", "fqtr"]
    valid = data.dropna(subset=keys)
    duplicates = valid.loc[valid.duplicated(keys, keep=False)]
    fiscal_groups = duplicates.groupby(keys, dropna=False)
    dates = fiscal_groups.datadate.nunique(dropna=False)
    period_valid = valid.dropna(subset=["datadate"])
    period_duplicates = period_valid.loc[period_valid.duplicated(["gvkey", "datadate"], keep=False)]
    period_groups = period_duplicates.groupby(["gvkey", "datadate"], dropna=False)
    amounts = period_groups[[income_field, "oancfy", "atq"]].nunique(dropna=False)
    fiscal_pairs = period_duplicates.drop_duplicates(["gvkey", "datadate", "fyearq", "fqtr"])
    pair_counts = fiscal_pairs.groupby(["gvkey", "datadate"]).size()
    range_dates = duplicates.datadate.dropna()
    return {
        "rows": len(data), "columns": len(data.columns), "id_whitespace_normalizations": spaces,
        "rows_with_missing_fiscal_key": len(data) - len(valid),
        "duplicate_fiscal_key_rows_valid_keys": len(duplicates),
        "duplicate_fiscal_key_share_valid_keys": len(duplicates) / len(valid) if len(valid) else None,
        "duplicate_fiscal_key_groups": len(dates),
        "groups_spanning_multiple_period_end_dates": int(dates.gt(1).sum()),
        "groups_with_same_period_end_date": int(dates.eq(1).sum()),
        "exact_duplicate_full_rows": int(frame.duplicated().sum()),
        "duplicate_company_period_end_rows_among_valid_fiscal_keys": len(period_duplicates),
        "duplicate_company_period_end_groups": len(pair_counts),
        "period_end_groups_with_conflicting_fiscal_labels": int(pair_counts.gt(1).sum()),
        "period_end_groups_with_different_inspected_amounts": int(amounts.gt(1).any(axis=1).sum()),
        "inspected_amount_fields": [income_field, "oancfy", "atq"],
        "missing_period_end_rows": int(data.datadate.isna().sum()),
        "duplicate_fiscal_group_period_end_range": [
            value.isoformat() if pd.notna(value) else None for value in [range_dates.min(), range_dates.max()]
        ],
        "action": "No rows changed or removed. Resolve fiscal-period identity before quarter arithmetic.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_csv", type=Path)
    parser.add_argument("--income-field", required=True, choices=["niq", "ibq"])
    parser.add_argument("--source-label", default="private-input")
    args = parser.parse_args()
    data = pd.read_csv(args.source_csv, dtype={"gvkey": str})
    digest = hashlib.sha256()
    with args.source_csv.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    print(json.dumps({"source_role": args.source_label, "sha256": digest.hexdigest(),
                      **audit_period_keys(data, args.income_field)}, indent=2))


if __name__ == "__main__":
    main()
