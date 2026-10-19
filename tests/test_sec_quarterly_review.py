"""Synthetic SEC durations, reported quarters and explicit mixed-filing guards."""

import json

import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline.sec_quarterly_review import (
    CFO,
    NI,
    review_sec_quarterly_snapshots,
    sec_quarterly_diagnostic,
)
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore


def contexts(dates=None, start="2019-07-01"):
    dates = (
        pd.date_range("2019-09-30", periods=8, freq=pd.offsets.QuarterEnd(), tz="UTC")
        if dates is None
        else pd.to_datetime(dates, utc=True)
    )
    flows = [6, 8, 10, 12, 5, 7, 9, 11]
    facts, filings = [], []
    for i, end in enumerate(dates):
        quarter, year = i % 4 + 1, 2020 + i // 4
        fiscal_start = pd.Timestamp(start, tz="UTC") if i < 4 else dates[3] + pd.Timedelta(days=1)
        accession = f"0000000042-20-{i + 1:06d}"
        form = "10-K" if quarter == 4 else "10-Q"
        filings.append({"accession": accession, "report_date": end, "form": form})
        base = {
            "cik": "0000000042",
            "namespace": "us-gaap",
            "unit": "USD",
            "accession": accession,
            "period_end": end,
            "source_fy": year,
            "source_fp": "FY" if quarter == 4 else f"Q{quarter}",
        }
        facts.append(
            {**base, "tag": "Assets", "period_start": pd.NaT, "duration_days": None, "value_text": str(100 + 10 * i)}
        )
        for tag, value in [(NI, 10 * quarter), (CFO, sum(flows[(i // 4) * 4 : i + 1]))]:
            facts.append(
                {
                    **base,
                    "tag": tag,
                    "period_start": fiscal_start,
                    "duration_days": (end - fiscal_start).days + 1,
                    "value_text": str(value),
                }
            )
        if quarter in (2, 3):
            begin = dates[i - 1] + pd.Timedelta(days=1)
            facts.append(
                {**base, "tag": NI, "period_start": begin, "duration_days": (end - begin).days + 1, "value_text": "10"}
            )
    frame = pd.DataFrame(facts)
    frame.duration_days = frame.duration_days.astype("Int64")
    return frame, pd.DataFrame(filings)


def test_ytd_difference_q4_and_new_year_reset_on_a_june_fiscal_calendar():
    facts, filings = contexts()
    output = sec_quarterly_diagnostic(facts, filings)
    np.testing.assert_allclose(output.operating_cash_flow_quarter, [6, 8, 10, 12, 5, 7, 9, 11])
    np.testing.assert_allclose(output.net_income, [10] * 8)
    assert output.cash_flow_previous_accession.iloc[1] == filings.accession.iloc[0]
    assert pd.isna(output.cash_flow_previous_accession.iloc[4])
    assert output.income_basis.iloc[3] == "annual_minus_q3_ytd"
    assert output.fiscal_quarter.tolist() == [1, 2, 3, 4] * 2
    assert output.ttm_operating_cash_flow.iloc[4] == 35
    assert output.accrual_quality.iloc[4] == pytest.approx(-5 / 120)
    assert output.calculation_ready.tolist() == [False] * 4 + [True] * 4
    assert output.available_at.isna().all()


def test_reported_quarter_cash_flow_is_not_differenced_again_and_difference_is_visible():
    facts, filings = contexts()
    direct = facts.loc[
        (facts.accession.eq(filings.accession.iloc[1])) & facts.tag.eq(NI) & facts.duration_days.le(120)
    ].copy()
    direct.tag, direct.value_text = CFO, "99"
    output = sec_quarterly_diagnostic(pd.concat([facts, direct]), filings)
    assert output.operating_cash_flow_quarter.iloc[1] == 99
    assert output.cash_flow_basis.iloc[1] == "reported_quarter"
    assert output.cash_flow_reported_minus_ytd_difference_text.iloc[1] == "91"
    assert pd.isna(output.cash_flow_previous_accession.iloc[1])


def test_53_week_fiscal_year_does_not_use_calendar_quarter_labels():
    dates = [
        "2021-12-25",
        "2022-03-26",
        "2022-06-25",
        "2022-10-01",
        "2022-12-31",
        "2023-04-01",
        "2023-07-01",
        "2023-09-30",
    ]
    facts, filings = contexts(dates, start="2021-09-26")
    output = sec_quarterly_diagnostic(facts, filings)
    assert output.fiscal_quarter.tolist() == [1, 2, 3, 4] * 2
    assert output.calculation_ready.tolist() == [False] * 4 + [True] * 4


def test_missing_filing_does_not_bridge_ytd_and_windows_recover():
    facts, filings = contexts()
    output = sec_quarterly_diagnostic(facts, filings.drop(index=1))
    assert pd.isna(output.operating_cash_flow_quarter.iloc[1])
    assert output.calculation_ready.tolist() == [False] * 5 + [True] * 2


def test_ytd_fiscal_start_change_blocks_difference():
    facts, filings = contexts()
    affected = facts.accession.eq(filings.accession.iloc[2]) & facts.tag.eq(CFO)
    facts.loc[affected, "period_start"] -= pd.Timedelta(days=1)
    facts.loc[affected, "duration_days"] += 1
    output = sec_quarterly_diagnostic(facts, filings)
    assert output.operating_cash_flow_quarter.iloc[2:4].isna().all()


@pytest.mark.parametrize("tag", [NI, CFO])
def test_ambiguous_context_is_not_deduplicated_or_replaced(tag):
    facts, filings = contexts()
    duplicate = facts.loc[facts.accession.eq(filings.accession.iloc[1]) & facts.tag.eq(tag)]
    if tag == NI:
        duplicate = duplicate.loc[duplicate.duration_days.le(120)]
    output = sec_quarterly_diagnostic(pd.concat([facts, duplicate]), filings)
    assert pd.isna(output.net_income.iloc[1] if tag == NI else output.operating_cash_flow_quarter.iloc[1])


def test_direct_quarter_start_mismatch_is_not_filled_from_ytd():
    facts, filings = contexts()
    mask = facts.accession.eq(filings.accession.iloc[1]) & facts.tag.eq(NI) & facts.duration_days.le(120)
    facts.loc[mask, "period_start"] += pd.Timedelta(days=1)
    facts.loc[mask, "duration_days"] -= 1
    output = sec_quarterly_diagnostic(facts, filings)
    assert pd.isna(output.net_income.iloc[1])
    assert output.income_basis.iloc[1] == "reported_quarter_start_mismatch"


@pytest.mark.parametrize("label", [None, "Q4", "FY"])
def test_missing_or_wrong_filing_fiscal_labels_are_not_inferred_from_months(label):
    facts, filings = contexts()
    facts.loc[facts.accession.eq(filings.accession.iloc[1]), "source_fp"] = label
    output = sec_quarterly_diagnostic(facts, filings)
    assert pd.isna(output.fiscal_quarter.iloc[1])
    assert pd.isna(output.net_income.iloc[1])
    assert output.calculation_ready.tolist() == [False] * 6 + [True] * 2


def test_amendments_stay_separate_and_duplicate_originals_are_rejected():
    facts, filings = contexts()
    amendment = filings.iloc[[1]].assign(accession="0000000042-20-999999", form="10-Q/A")
    pd.testing.assert_frame_equal(
        sec_quarterly_diagnostic(facts, filings), sec_quarterly_diagnostic(facts, pd.concat([filings, amendment]))
    )
    with pytest.raises(ValueError, match="Multiple original"):
        sec_quarterly_diagnostic(facts, pd.concat([filings, amendment.assign(form="10-Q")]))


def test_input_immutability_order_and_future_mutation():
    facts, filings = contexts()
    original = facts.copy(deep=True)
    baseline = sec_quarterly_diagnostic(facts, filings)
    pd.testing.assert_frame_equal(facts, original)
    pd.testing.assert_frame_equal(
        baseline, sec_quarterly_diagnostic(facts.sample(frac=1, random_state=1), filings.sample(frac=1, random_state=1))
    )
    facts.loc[facts.accession.eq(filings.accession.iloc[-1]), "value_text"] = "9999"
    pd.testing.assert_frame_equal(baseline.iloc[:-1], sec_quarterly_diagnostic(facts, filings).iloc[:-1])


def test_missing_exact_unit_is_not_converted_and_companies_cannot_be_pooled():
    facts, filings = contexts()
    assert not sec_quarterly_diagnostic(facts, filings, unit="EUR").calculation_ready.any()
    with pytest.raises(ValueError, match="one nonempty"):
        sec_quarterly_diagnostic(pd.concat([facts, facts.assign(cik="0000000043")]), filings)


def test_negative_cash_flow_is_preserved_and_overflow_rejected():
    facts, filings = contexts()
    facts.loc[facts.tag.eq(CFO), "value_text"] = facts.loc[facts.tag.eq(CFO), "value_text"].map(lambda v: str(-int(v)))
    assert sec_quarterly_diagnostic(facts, filings).operating_cash_flow_quarter.lt(0).all()
    facts.loc[facts.tag.eq("Assets"), "value_text"] = "1e1000"
    with pytest.raises(ValueError, match="finite float"):
        sec_quarterly_diagnostic(facts, filings)


def capture(store):
    facts, filings = contexts()
    recent = {
        "accessionNumber": filings.accession.tolist(),
        "reportDate": filings.report_date.dt.strftime("%Y-%m-%d").tolist(),
        "filingDate": ["2021-08-01"] * 8,
        "form": filings.form.tolist(),
    }
    payload = {"cik": 42, "entityName": "Explicitly Synthetic", "facts": {"us-gaap": {}}}
    for tag, part in facts.groupby("tag"):
        rows = []
        for _, row in part.iterrows():
            item = {
                "accn": row.accession,
                "form": filings.loc[filings.accession.eq(row.accession), "form"].iloc[0],
                "filed": "2021-08-01",
                "end": row.period_end.strftime("%Y-%m-%d"),
                "val": int(row.value_text),
                "fy": int(row.source_fy),
                "fp": row.source_fp,
            }
            if pd.notna(row.period_start):
                item["start"] = row.period_start.strftime("%Y-%m-%d")
            rows.append(item)
        payload["facts"]["us-gaap"][tag] = {"units": {"USD": rows}}
    source = store.capture(
        "sec",
        {"kind": "companyfacts", "cik": "0000000042"},
        json.dumps(payload).encode(),
        observed_at="2022-01-01T00:00:00Z",
    )
    submission = store.capture(
        "sec",
        {"kind": "submissions", "cik": "0000000042"},
        json.dumps({"cik": 42, "filings": {"recent": recent, "files": []}}).encode(),
        observed_at="2022-01-01T00:00:00Z",
    )
    return source, submission


def test_verified_source_wrapper_replay_and_corruption(tmp_path, monkeypatch):
    import requests

    def no_network(*args, **kwargs):
        pytest.fail("Offline review attempted a network request")

    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    store = SnapshotStore(tmp_path)
    source, submission = capture(store)
    result = review_sec_quarterly_snapshots(store, source, submission)
    assert result == review_sec_quarterly_snapshots(store, source, submission)
    frame = pd.read_parquet(
        store.root / result["tables"]["quarterly_review"]["path"], use_threads=False, pre_buffer=False
    )
    assert frame.calculation_ready.sum() == 4
    (store.root / result["tables"]["quarterly_review"]["path"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        review_sec_quarterly_snapshots(store, source, submission)


def test_filing_date_conflict_remains_a_source_gate(tmp_path):
    store = SnapshotStore(tmp_path)
    source, submission = capture(store)
    payload = store.read_payload(source)
    payload["facts"]["us-gaap"][NI]["units"]["USD"][0]["filed"] = "2021-08-02"
    conflict = store.capture(
        "sec", json.loads(source["request_json"]), json.dumps(payload).encode(), observed_at="2022-01-01T00:00:00Z"
    )
    with pytest.raises(ValueError, match="metadata conflicts"):
        review_sec_quarterly_snapshots(store, conflict, submission)
