"""Synthetic noncalendar SEC YTD and Q4 reconstruction; no network/contact."""

import json
from tempfile import TemporaryDirectory

import pandas as pd

from systematic_alpha_lab.data_pipeline.sec_quarterly_review import CFO, NI, review_sec_quarterly_snapshots
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    dates = pd.date_range("2019-09-30", periods=8, freq=pd.offsets.QuarterEnd(), tz="UTC")
    cash = [6, 8, 10, 12, 5, 7, 9, 11]
    recent = {name: [] for name in ("accessionNumber", "form", "filingDate", "reportDate")}
    concepts = {tag: {"units": {"USD": []}} for tag in ("Assets", NI, CFO)}
    for i, end in enumerate(dates):
        q, year = i % 4 + 1, 2020 + i // 4
        start = pd.Timestamp("2019-07-01", tz="UTC") if i < 4 else dates[3] + pd.Timedelta(days=1)
        acc = f"0000000042-20-{i + 1:06d}"
        form = "10-K" if q == 4 else "10-Q"
        base = {
            "accn": acc,
            "filed": "2021-08-01",
            "form": form,
            "end": str(end.date()),
            "fy": year,
            "fp": "FY" if q == 4 else f"Q{q}",
        }
        for name, value in zip(recent, [acc, form, "2021-08-01", str(end.date())]):
            recent[name].append(value)
        concepts["Assets"]["units"]["USD"].append({**base, "val": 100 + 10 * i})
        for tag, value in ((NI, 10 * q), (CFO, sum(cash[(i // 4) * 4 : i + 1]))):
            concepts[tag]["units"]["USD"].append({**base, "start": str(start.date()), "val": value})
        if q in (2, 3):
            concepts[NI]["units"]["USD"].append(
                {**base, "start": str((dates[i - 1] + pd.Timedelta(days=1)).date()), "val": 10}
            )
    payloads = [
        {"cik": 42, "entityName": "Explicitly Synthetic", "facts": {"us-gaap": concepts}},
        {"cik": 42, "filings": {"recent": recent, "files": []}},
    ]
    with TemporaryDirectory() as root:
        store = SnapshotStore(root)
        records = [
            store.capture(
                "sec",
                {"kind": kind, "cik": "0000000042"},
                json.dumps(payload).encode(),
                observed_at="2022-01-01T00:00:00Z",
            )
            for kind, payload in zip(("companyfacts", "submissions"), payloads)
        ]
        manifest = review_sec_quarterly_snapshots(store, *records)
        assert manifest == review_sec_quarterly_snapshots(store, *records)
        frame = pd.read_parquet(
            store.root / manifest["tables"]["quarterly_review"]["path"], use_threads=False, pre_buffer=False
        )
        assert frame.operating_cash_flow_quarter.tolist() == cash
        assert frame.calculation_ready.sum() == 4
        print(
            json.dumps(
                {
                    "synthetic_only": True,
                    "network_calls": 0,
                    "exact_replay": True,
                    "quarter_rows": len(frame),
                    "ttm_candidate_rows": int(frame.calculation_ready.sum()),
                }
            )
        )


if __name__ == "__main__":
    main()
