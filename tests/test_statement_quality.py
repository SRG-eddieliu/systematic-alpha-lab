import json
from copy import deepcopy

import pandas as pd
import pytest
from test_fundamental_snapshots import NOW, Feed

from systematic_alpha_lab.data_pipeline.fundamental_snapshots import ingest_fundamentals
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.data_pipeline.statement_quality import amount_status, profile_fundamental_receipts


@pytest.mark.parametrize("value,status", [
    (None, "missing"), (pd.NA, "missing"), ("None", "missing"), ("NaN", "missing"),
    ("", "missing"), ("0", "finite"), ("-1.25e5", "finite"),
    ("Infinity", "nonfinite"), ("-inf", "nonfinite"), ("unknown", "nonnumeric"), (True, "nonnumeric"),
    ([1, 2], "nonnumeric"), ({"amount": "1"}, "nonnumeric"),
])
def test_amount_quality_does_not_confuse_missing_zero_and_invalid(value, status):
    assert amount_status(value) == status


def test_receipt_quality_is_pinned_read_only_and_keeps_unknown_eligibility(tmp_path, monkeypatch):
    receipts = ingest_fundamentals(Feed(), SnapshotStore(tmp_path), symbols=["SYNTH"],
                                   min_interval_seconds=0, clock=lambda: NOW)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    import socket
    def denied(*args, **kwargs):
        raise AssertionError("Network prohibited")
    monkeypatch.setattr(socket.socket, "connect", denied)
    report = profile_fundamental_receipts(tmp_path, receipts)
    assert len(report["tables"]) == 6
    assert all(row["available_at_supplied_rows"] == 0 for row in report["tables"])
    assert all(row["eligibility"] == "not_certified" for row in report["tables"])
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()} == before
    changed = deepcopy(receipts)
    changed[0]["tables"]["annual"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="differs"):
        profile_fundamental_receipts(tmp_path, changed)
    with pytest.raises(ValueError, match="Duplicate"):
        profile_fundamental_receipts(tmp_path, receipts * 2)
    changed = deepcopy(receipts)
    changed[0]["provenance"]["extra"] = "changed"
    with pytest.raises(ValueError, match="complete manifest"):
        profile_fundamental_receipts(tmp_path, changed)
    json.dumps(report, allow_nan=False)
