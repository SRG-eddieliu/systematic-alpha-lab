"""The private audit reconciles raw values and rejects ambiguous identity."""
import csv
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def audit_script():
    path = Path(__file__).parents[1] / "examples" / "audit_legacy_beneish.py"
    spec = importlib.util.spec_from_file_location("beneish_audit_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def synthetic_sources(tmp_path, audit_script):
    raw_rows, saved_rows = [], []
    ends = ["2018-12-31", "2019-03-31", "2019-06-30", "2019-09-30", "2019-12-31", "2020-03-31"]
    for entity, ticker in enumerate(audit_script.TICKERS, start=1):
        for (year, quarter), end in zip(audit_script.PERIODS, ends):
            row = {"gvkey": f"{entity:06}", "datadate": end, "tic": ticker,
                   "fyearq": year, "fqtr": quarter, "curcdq": "USD",
                   "rectq": 10, "saleq": 100, "cogsq": 60, "actq": 40,
                   "ppentq": 50, "atq": 100, "dpq": 5, "xsgaq": 10,
                   "dlttq": 10, "lctq": 20}
            raw_rows.append(row)
            saved = {"gvkey_beneish": f"{entity}.0", "datadate_beneish": end,
                     "tic": ticker, "fyearq": year, "fqtr": quarter, "curcdq_beneish": "USD"}
            for field in audit_script.FIELD_MAP.values():
                saved[audit_script.SAVED_ALIASES.get(field, field)] = row[field]
            # Independent hand case: unchanged amounts => seven ratios 1,
            # balance-sheet change proxy 0, M=-2.48 and sigmoid(-.26).
            saved.update({name: 1 for name in audit_script.RATIOS})
            saved.update(TATA=0, beneish_mscore=-2.48,
                         beneish_probability=0.4353637081969708, manipulator_flag="False")
            saved_rows.append(saved)
    raw, saved = tmp_path / "raw.csv", tmp_path / "saved.csv"
    write_csv(raw, raw_rows)
    write_csv(saved, saved_rows)
    return raw, saved, raw_rows, saved_rows


def test_fixed_audit_reconciles_known_values_and_preserves_sources(audit_script, synthetic_sources):
    raw, saved, _, _ = synthetic_sources
    before = raw.read_bytes(), saved.read_bytes()
    result, rows = audit_script.audit(raw, saved)
    assert result["status"] == "passed"
    assert result["reconciliation_counts"]["stable_identity_date_fiscal_matches"] == 18
    assert result["reconciliation_counts"]["calculation_ready_targets"] == len(rows) == 15
    assert result["source_files_unchanged"]
    assert result["context_warning_counts"] == {"missing_or_invalid_metadata:unit": 15}
    assert (raw.read_bytes(), saved.read_bytes()) == before


def test_raw_input_change_cannot_be_hidden_by_saved_outputs(audit_script, synthetic_sources):
    raw, saved, raw_rows, _ = synthetic_sources
    raw_rows[2]["actq"] = 45
    write_csv(raw, raw_rows)
    result, _ = audit_script.audit(raw, saved)
    assert result["status"] == "failed"
    assert result["raw_saved_input_comparisons"]["actq"]["mismatches"] == 1
    assert result["saved_output_comparisons"]["TATA"]["mismatches"] > 0


def test_duplicate_selected_quarter_is_not_silently_deduplicated(audit_script, synthetic_sources):
    raw, saved, raw_rows, _ = synthetic_sources
    write_csv(raw, raw_rows + [raw_rows[0]])
    result, _ = audit_script.audit(raw, saved)
    assert result["status"] == "failed"
    assert result["error_counts"]["selected_key_missing_or_nonunique"] == 1


def test_ticker_match_cannot_override_stable_entity_mismatch(audit_script, synthetic_sources):
    raw, saved, _, saved_rows = synthetic_sources
    saved_rows[1]["gvkey_beneish"] = "999"
    write_csv(saved, saved_rows)
    result, _ = audit_script.audit(raw, saved)
    assert result["status"] == "failed"
    assert result["error_counts"]["raw_saved_stable_key_mismatch"] == 1


def test_changed_saved_score_is_detected(audit_script, synthetic_sources):
    raw, saved, _, saved_rows = synthetic_sources
    saved_rows[1]["beneish_mscore"] = -1
    write_csv(saved, saved_rows)
    result, _ = audit_script.audit(raw, saved)
    assert result["status"] == "failed"
    assert result["saved_output_comparisons"]["beneish_mscore"]["mismatches"] == 1
