"""Synthetic monthly adjustment and exact-replay example; never calls a provider."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from systematic_alpha_lab.data_pipeline.monthly_price_snapshots import price_request, replay_monthly_prices
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    dates = ["2020-01-31", "2020-02-28", "2020-03-31", "2020-04-15"]
    series = {}
    for date, close, adjusted in zip(dates, [100, 55, 60, 70], [10, 11, 12, 14]):
        series[date] = {
            "1. open": str(close),
            "2. high": str(close + 1),
            "3. low": str(close - 1),
            "4. close": str(close),
            "5. adjusted close": str(adjusted),
            "6. volume": "1000",
            "7. dividend amount": "0",
        }
    payload = {
        "Meta Data": {"2. Symbol": "SYNTH", "3. Last Refreshed": dates[-1], "4. Time Zone": "US/Eastern"},
        "Monthly Adjusted Time Series": series,
    }
    with TemporaryDirectory() as root:
        store = SnapshotStore(root)
        record = store.capture(
            "alpha_vantage", price_request("SYNTH"), json.dumps(payload).encode(), observed_at="2020-04-16T18:00Z"
        )
        manifest = replay_monthly_prices(store, record)
        assert manifest == replay_monthly_prices(store, store.get(record["id"]))
        frame = pd.read_parquet(
            Path(root) / manifest["tables"]["monthly_prices"]["path"], use_threads=False, pre_buffer=False
        )
        assert frame.adjusted_close_change_1m.iloc[1] == 0.1
        assert frame.forward_adjusted_close_change_1m.iloc[-2:].isna().all()
        assert frame.available_at.isna().all()
        print(
            json.dumps(
                {
                    "synthetic_only": True,
                    "network_calls": 0,
                    "exact_replay": True,
                    "monthly_rows": len(frame),
                    "eligible_forward_changes": int(frame.forward_adjusted_close_change_1m.notna().sum()),
                }
            )
        )


if __name__ == "__main__":
    main()
