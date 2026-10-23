"""Reconcile a fixed private sample with saved Q07 outputs, entirely offline.

Only aggregate evidence is written by default. Optional row-level output must
remain outside this checkout. Source CSVs are opened read-only and fingerprinted
before and after the audit; no data is downloaded, repaired, or deduplicated.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

TICKERS = ("AAPL", "MSFT", "IBM")
PERIODS = ((2018, 4), (2019, 1), (2019, 2), (2019, 3), (2019, 4), (2020, 1))
TOLERANCE = 1e-10
FIELD_MAP = {
    "receivables": "rectq", "sales": "saleq", "cost_of_goods_sold": "cogsq",
    "current_assets": "actq", "net_ppe": "ppentq", "total_assets": "atq",
    "depreciation": "dpq", "sga_expense": "xsgaq", "long_term_debt": "dlttq",
    "current_liabilities": "lctq",
}
SAVED_ALIASES = {"saleq": "saleq_beneish", "atq": "atq_beneish", "dlttq": "dlttq_beneish"}
RATIOS = ("DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI", "TATA")
OUTPUT_FIELDS = (*RATIOS, "beneish_mscore", "beneish_probability")
REFERENCE_NOTEBOOK_SHA256 = "d8191cc510d4957e3a53477405ef9fcafb64c98f9c22434bc18ad7628ef3f359"


def fingerprint(path: Path) -> dict[str, Any]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("File changed while its fingerprint was being read")
    return {"sha256": digest.hexdigest(), "bytes": after.st_size, "mtime_ns": after.st_mtime_ns}


def integer(value: str) -> int | None:
    try:
        number = Decimal(value.strip())
        if not number.is_finite() or number != number.to_integral_value():
            return None
        return int(number)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def identity(value: str) -> str | None:
    number = integer(value)
    return str(number) if number is not None and number > 0 else None


def period_end(value: str) -> str | None:
    try:
        parts = re.split(r"[-/]", value.strip())
        return date(*(int(part) for part in parts)).isoformat() if len(parts) == 3 else None
    except (TypeError, ValueError, OverflowError):
        return None


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def boolean(value: str) -> bool | None:
    return {"true": True, "false": False}.get(value.strip().lower())


def inspect_csv(path: Path, *, saved: bool) -> tuple[dict[str, Any], dict]:
    suffix = "_beneish" if saved else ""
    id_field, date_field, currency_field = (f"{field}{suffix}" for field in ("gvkey", "datadate", "curcdq"))
    inputs = {field: SAVED_ALIASES.get(field, field) if saved else field for field in FIELD_MAP.values()}
    required = {id_field, date_field, currency_field, "tic", "fyearq", "fqtr", *inputs.values()}
    if saved:
        required.update((*OUTPUT_FIELDS, "manipulator_flag"))
    selected: dict = defaultdict(list)
    fiscal_counts: Counter = Counter()
    stable_counts: Counter = Counter()
    missing: Counter = Counter()
    nonfinite: Counter = Counter()
    output_missing: Counter = Counter()
    output_nonfinite: Counter = Counter()
    flags: Counter = Counter()
    bad_key_rows = rows = missing_currency = missing_score_false_flag = 0
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if not required.issubset(headers):
            raise ValueError(f"Missing required {'saved' if saved else 'raw'} columns: {sorted(required - set(headers))}")
        for row in reader:
            rows += 1
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed CSV row width; no rows were repaired")
            entity = identity(row[id_field])
            end = period_end(row[date_field])
            year, quarter = integer(row["fyearq"]), integer(row["fqtr"])
            valid_fiscal = entity is not None and year is not None and 1 <= year <= 9999 and quarter in (1, 2, 3, 4)
            if valid_fiscal:
                fiscal_counts[(entity, year, quarter)] += 1
                if end is not None:
                    stable_counts[(entity, end, year, quarter)] += 1
            if not valid_fiscal or end is None:
                bad_key_rows += 1
            missing_currency += not bool(row[currency_field].strip())
            for field, column in inputs.items():
                value = row[column]
                if not value.strip():
                    missing[field] += 1
                elif number(value) is None:
                    nonfinite[field] += 1
            if saved:
                for field in OUTPUT_FIELDS:
                    value = row[field]
                    if not value.strip():
                        output_missing[field] += 1
                    elif number(value) is None:
                        output_nonfinite[field] += 1
                flags[str(boolean(row["manipulator_flag"]))] += 1
                missing_score_false_flag += not row["beneish_mscore"].strip() and boolean(row["manipulator_flag"]) is False
            ticker = row["tic"].strip().upper().replace(".", "-")
            if ticker in TICKERS and (year, quarter) in PERIODS:
                selected[(ticker, year, quarter)].append(row)
    selected_nonunique_stable_keys = 0
    for matches in selected.values():
        for row in matches:
            key = (identity(row[id_field]), period_end(row[date_field]),
                   integer(row["fyearq"]), integer(row["fqtr"]))
            selected_nonunique_stable_keys += None in key or stable_counts[key] != 1
    quality = {
        "rows": rows, "columns": len(headers), "invalid_or_missing_stable_key_rows": bad_key_rows,
        "valid_fiscal_key_groups": len(fiscal_counts),
        "duplicate_fiscal_key_groups": sum(count > 1 for count in fiscal_counts.values()),
        "duplicate_fiscal_key_rows": sum(count for count in fiscal_counts.values() if count > 1),
        "valid_stable_period_key_groups": len(stable_counts),
        "duplicate_stable_period_key_groups": sum(count > 1 for count in stable_counts.values()),
        "duplicate_stable_period_key_rows": sum(count for count in stable_counts.values() if count > 1),
        "missing_input_counts": dict(missing), "invalid_or_nonfinite_input_counts": dict(nonfinite),
        "missing_currency_rows": missing_currency, "unit_column_present": "unit" in headers,
        "selected_rows": sum(map(len, selected.values())),
        "selected_policy_keys_with_nonunique_rows": sum(len(value) != 1 for value in selected.values()),
        "selected_rows_without_unique_global_stable_key": selected_nonunique_stable_keys,
    }
    if saved:
        quality.update(saved_output_missing_counts=dict(output_missing),
                       saved_output_invalid_or_nonfinite_counts=dict(output_nonfinite),
                       saved_flag_counts=dict(flags), missing_m_score_with_false_flag=missing_score_false_flag)
    return quality, selected


def comparison() -> dict[str, Any]:
    return {"comparisons": 0, "mismatches": 0, "missing_or_nonfinite_pairs": 0, "max_absolute_error": None}


def compare(stats: dict[str, Any], actual: Any, expected: Any) -> None:
    stats["comparisons"] += 1
    a, b = number(actual), number(expected)
    if a is None or b is None:
        stats["missing_or_nonfinite_pairs"] += 1
        stats["mismatches"] += 1
        return
    difference = abs(a - b)
    previous = stats["max_absolute_error"]
    stats["max_absolute_error"] = difference if previous is None else max(previous, difference)
    stats["mismatches"] += difference > TOLERANCE


def audit(raw: Path, saved: Path) -> tuple[dict[str, Any], list]:
    from systematic_alpha_lab.factor_research import beneish

    code = {"cli": Path(__file__).resolve(), "beneish_module": Path(beneish.__file__).resolve()}
    inputs_before = {"raw": fingerprint(raw), "saved": fingerprint(saved)}
    code_before = {name: fingerprint(path) for name, path in code.items()}
    raw_quality, raw_rows = inspect_csv(raw, saved=False)
    saved_quality, saved_rows = inspect_csv(saved, saved=True)
    errors: Counter = Counter()
    for label, quality in (("raw", raw_quality), ("saved", saved_quality)):
        if quality["selected_rows_without_unique_global_stable_key"]:
            errors[f"{label}_selected_stable_key_not_unique"] = quality["selected_rows_without_unique_global_stable_key"]
    lineage = {field: comparison() for field in FIELD_MAP.values()}
    outputs = {field: comparison() for field in OUTPUT_FIELDS}
    reconciled = {}
    stable_matches = currency_matches = ready = flag_compared = flag_mismatches = 0
    warnings: Counter = Counter()
    reasons: Counter = Counter()
    private_rows = []
    for ticker in TICKERS:
        for year, quarter in PERIODS:
            key = (ticker, year, quarter)
            if len(raw_rows.get(key, [])) != 1 or len(saved_rows.get(key, [])) != 1:
                errors["selected_key_missing_or_nonunique"] += 1
                continue
            source, reference = raw_rows[key][0], saved_rows[key][0]
            source_key = (identity(source["gvkey"]), period_end(source["datadate"]), year, quarter)
            reference_key = (identity(reference["gvkey_beneish"]), period_end(reference["datadate_beneish"]), year, quarter)
            if None in source_key or source_key != reference_key:
                errors["raw_saved_stable_key_mismatch"] += 1
                continue
            stable_matches += 1
            if source["curcdq"].strip() == reference["curcdq_beneish"].strip() and source["curcdq"].strip():
                currency_matches += 1
            else:
                errors["raw_saved_currency_mismatch"] += 1
            record = {"entity_id": source_key[0], "period_end": source_key[1],
                      "fiscal_year": year, "fiscal_quarter": quarter, "currency": source["curcdq"].strip()}
            for target, field in FIELD_MAP.items():
                record[target] = number(source[field])
                compare(lineage[field], source[field], reference[SAVED_ALIASES.get(field, field)])
            # Units are not supplied by these CSVs; do not invent a unit.
            reconciled[key] = (record, reference)
    for ticker in TICKERS:
        previous = reconciled.get((ticker, *PERIODS[0]))
        for year, quarter in PERIODS[1:]:
            pair = reconciled.get((ticker, year, quarter))
            if pair is None or previous is None:
                errors["target_or_previous_input_unavailable"] += 1
                previous = pair
                continue
            current, reference = pair
            result = beneish.legacy_q07_quarterly_proxy(current, previous[0])
            previous = pair
            warnings.update(result.get("context_warnings", []))
            reasons.update(result["reasons"])
            ready += bool(result["calculation_ready"])
            expected = {field: reference[field] for field in OUTPUT_FIELDS}
            actual = {**result["ratios"], "beneish_mscore": result["m_score"],
                      "beneish_probability": result["legacy_logistic_score"]}
            for field in OUTPUT_FIELDS:
                compare(outputs[field], actual[field], expected[field])
            expected_flag = boolean(reference["manipulator_flag"])
            flag_compared += 1
            flag_mismatches += expected_flag is None or result["flag"] is None or result["flag"] != expected_flag
            private_rows.append({"ticker": ticker, "fiscal_year": year, "fiscal_quarter": quarter,
                                 "entity_id": current["entity_id"], "period_end": current["period_end"],
                                 "calculated": result, "saved": {**expected, "flag": expected_flag}})
    inputs_after = {"raw": fingerprint(raw), "saved": fingerprint(saved)}
    code_after = {name: fingerprint(path) for name, path in code.items()}
    unchanged = inputs_before == inputs_after
    code_unchanged = code_before == code_after
    passed = (not errors and not reasons and unchanged and code_unchanged and ready == 15
              and stable_matches == currency_matches == 18 and flag_compared == 15 and not flag_mismatches
              and not any(stat["mismatches"] for stat in [*lineage.values(), *outputs.values()]))
    receipt = {
        "audit": "private_legacy_q07_fixed_sample_v1", "status": "passed" if passed else "failed",
        "aggregate_only": True, "definition": "legacy_q07_quarterly_proxy_v1",
        "reference_notebook_sha256": REFERENCE_NOTEBOOK_SHA256,
        "selected_policy": {"tickers": list(TICKERS), "input_fiscal_periods": list(PERIODS),
                            "warmup_fiscal_period": list(PERIODS[0]), "expected_input_rows": 18,
                            "expected_target_rows": 15, "join_identity": ["gvkey", "datadate", "fyearq", "fqtr"],
                            "ticker_role": "sample selection only; never substitutes for stable identity",
                            "duplicate_action": "fail selected key; no deduplication or repair"},
        "field_map": {target: {"raw": field, "saved": SAVED_ALIASES.get(field, field)} for target, field in FIELD_MAP.items()},
        "tolerance": {"absolute": TOLERANCE, "relative": 0.0},
        "input_paths": {"raw": str(raw), "saved": str(saved)},
        "input_fingerprints_before": inputs_before, "input_fingerprints_after": inputs_after,
        "source_files_unchanged": unchanged,
        "source_code_paths": {name: str(path) for name, path in code.items()},
        "source_code_fingerprints_before": code_before, "source_code_fingerprints_after": code_after,
        "source_code_unchanged": code_unchanged,
        "source_quality": {"raw": raw_quality, "saved": saved_quality},
        "reconciliation_counts": {"stable_identity_date_fiscal_matches": stable_matches,
                                  "currency_matches": currency_matches, "calculation_ready_targets": ready,
                                  "flag_comparisons": flag_compared, "flag_mismatches": flag_mismatches},
        "raw_saved_input_comparisons": lineage, "saved_output_comparisons": outputs,
        "error_counts": dict(errors), "calculation_reason_counts": dict(reasons),
        "context_warning_counts": dict(warnings),
        "limitations": ["Saved outputs are a legacy reconciliation baseline, not independent model truth.",
                        "Quarterly row-lag proxy; no annual/TTM or adjusted-M definition supplied.",
                        "Units and publication availability are unverified; currency is caller-declared.",
                        "No historical constituent reconstruction, regression/composite validation, or alpha test.",
                        "No source repair, mutation, network access, or data redistribution."],
    }
    return receipt, private_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True, help="Private raw_data_beneish.csv")
    parser.add_argument("--saved", type=Path, required=True, help="Private saved Q07 merged CSV")
    parser.add_argument("--output", type=Path, required=True, help="New aggregate JSON receipt; refuses overwrite")
    parser.add_argument("--private-rows", type=Path, help="Optional new private JSON outside this checkout")
    args = parser.parse_args()
    raw, saved, output = (path.expanduser().resolve() for path in (args.raw, args.saved, args.output))
    private_output = args.private_rows.expanduser().resolve() if args.private_rows else None
    checkout = Path(__file__).resolve().parents[1]
    destinations = [output] + ([private_output] if private_output else [])
    if len(set(destinations)) != len(destinations) or any(path in (raw, saved) or path.exists() for path in destinations):
        parser.error("Outputs must be distinct new files and cannot overwrite a source")
    if private_output and private_output.is_relative_to(checkout):
        parser.error("Private row-level output must remain outside the checkout")
    try:
        receipt, rows = audit(raw, saved)
        receipt["private_row_output_requested"] = private_output is not None
        # Serialize strictly before opening a destination; receipts contain no NaN/Inf.
        payload = json.dumps(receipt, indent=2, allow_nan=False) + "\n"
        row_payload = json.dumps(rows, indent=2, allow_nan=False) + "\n" if private_output else None
        for path in destinations:
            path.parent.mkdir(parents=True, exist_ok=True)
        if private_output:
            with private_output.open("x", encoding="utf-8") as stream:
                stream.write(row_payload)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        parser.exit(2, f"Audit could not complete: {exc}\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(output),
                      "calculation_ready_targets": receipt["reconciliation_counts"]["calculation_ready_targets"]}))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
