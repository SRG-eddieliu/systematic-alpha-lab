import importlib.util
from pathlib import Path

import pandas as pd


def test_key_audit_distinguishes_period_identity_from_duplicate_rows():
    path = Path(__file__).resolve().parents[1] / "examples" / "audit_financial_period_keys.py"
    spec = importlib.util.spec_from_file_location("period_audit", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    frame = pd.DataFrame({
        "gvkey": ["a", "a", "a", "b", "b", "c"],
        "fyearq": [2020, 2020, 2020, 2020, 2020, None],
        "fqtr": [1, 1, 2, 1, 1, 1],
        "datadate": ["2020-03-31", "2020-04-30", "2020-04-30", "2020-03-31", "2020-03-31", "2020-03-31"],
        "niq": [1, 2, 3, 4, 4, 5], "oancfy": [10, 20, 30, 40, 40, 50], "atq": 100,
    })
    original = frame.copy(deep=True)
    result = module.audit_period_keys(frame, "niq")
    pd.testing.assert_frame_equal(original, frame)
    assert result["duplicate_fiscal_key_rows_valid_keys"] == 4
    assert result["duplicate_fiscal_key_groups"] == 2
    assert result["groups_spanning_multiple_period_end_dates"] == 1
    assert result["groups_with_same_period_end_date"] == 1
    assert result["exact_duplicate_full_rows"] == 1
    assert result["period_end_groups_with_conflicting_fiscal_labels"] == 1
    assert result["period_end_groups_with_different_inspected_amounts"] == 1
    assert result["rows_with_missing_fiscal_key"] == 1
