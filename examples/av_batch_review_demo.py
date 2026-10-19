"""Three synthetic fiscal calendars, one offline batch and an exact replay."""
import json
from tempfile import TemporaryDirectory

import pandas as pd

from systematic_alpha_lab.data_pipeline.batch_review import review_fundamental_batch
from systematic_alpha_lab.data_pipeline.fundamental_review import FIELDS
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def main():
    calendars = {
        "SYN-CAL": pd.date_range("2021-12-31", periods=9, freq=pd.offsets.QuarterEnd()),
        "SYN-JUN": pd.date_range("2021-06-30", periods=9, freq=pd.offsets.QuarterEnd()),
        "SYN-WEEK": pd.to_datetime(["2021-09-25", "2021-12-25", "2022-03-26", "2022-06-25",
                                     "2022-10-01", "2022-12-31", "2023-04-01", "2023-07-01", "2023-09-30"]),
    }
    with TemporaryDirectory() as root:
        store = SnapshotStore(root)
        for symbol, dates in calendars.items():
            for function, field in FIELDS.items():
                flow = 10 if function == "INCOME_STATEMENT" else 8
                quarterly = [{"fiscalDateEnding": date.strftime("%Y-%m-%d"), "reportedCurrency": "USD",
                              field: str(100 + 10 * i if function == "BALANCE_SHEET" else flow)}
                             for i, date in enumerate(dates)]
                if function == "CASH_FLOW":
                    for row in quarterly:
                        row["netIncome"] = "10"
                annual = [{**quarterly[i], field: quarterly[i][field] if function == "BALANCE_SHEET" else str(4 * flow)}
                          for i in (0, 4, 8)]
                if function == "CASH_FLOW":
                    for row in annual:
                        row["netIncome"] = "40"
                payload = {"symbol": symbol, "annualReports": annual, "quarterlyReports": quarterly}
                store.capture("alpha_vantage", {"symbol": symbol, "function": function}, json.dumps(payload).encode(),
                              observed_at="2025-01-01T00:00:00Z")
        result = review_fundamental_batch(store, symbols=list(calendars))
        replay = review_fundamental_batch(store, symbols=list(calendars), snapshot_ids=result["selection"])
        assert replay == result
        assert result["status"] == "complete"
        assert all(row["ttm_candidate_rows"] == 5 for row in result["summary"])
        print(json.dumps({"synthetic_only": True, "network_calls": 0, "exact_replay": True,
                          "company_coverage": result["summary"]}, indent=2))


if __name__ == "__main__":
    main()
