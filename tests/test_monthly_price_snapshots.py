"""Synthetic split/dividend, incomplete-month, source-mode and replay contracts."""

import json
from copy import deepcopy
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline.alpha_vantage_rest import (
    AlphaVantageError,
    AlphaVantageRESTClient,
    JSONResponse,
)
from systematic_alpha_lab.data_pipeline.monthly_price_snapshots import (
    FUNCTION,
    SERIES,
    ingest_monthly_prices,
    normalize_monthly_prices,
    price_request,
    replay_monthly_prices,
)
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

NOW = pd.Timestamp("2020-04-16T18:00Z")
DATES = ["2019-11-29", "2019-12-31", "2020-01-31", "2020-02-28", "2020-03-31", "2020-04-15"]


def payload(symbol="SYNTH"):
    rows = {}
    for date, close, adjusted, dividend in zip(
        DATES, [100, 110, 55, 60, 63, 70], [10, 11, 11, 12, 12.6, 14], [0, 0, 1, 0, 0, 0]
    ):
        rows[date] = {
            "1. open": str(close),
            "2. high": str(close + 1),
            "3. low": str(close - 1),
            "4. close": str(close),
            "5. adjusted close": str(adjusted),
            "6. volume": "1000",
            "7. dividend amount": str(dividend),
        }
    return {
        "Meta Data": {
            "1. Information": "Explicitly synthetic monthly adjusted data",
            "2. Symbol": symbol,
            "3. Last Refreshed": DATES[-1],
            "4. Time Zone": "US/Eastern",
        },
        SERIES: rows,
    }


def record(observed=NOW, symbol="SYNTH", mode="user"):
    return {
        "provider": "alpha_vantage",
        "id": "synthetic",
        "request_json": json.dumps(price_request(symbol, mode)),
        "observed_at": observed.isoformat(),
    }


class Client:
    def __init__(self, source=None, body=None, failure=None):
        self.source, self.body, self.failure, self.calls = source, body, failure, []

    def fetch_json_response(self, function, params):
        self.calls.append((function, params))
        if self.failure:
            raise self.failure
        source = self.source if self.source is not None else payload(params["symbol"])
        return JSONResponse(source, self.body or json.dumps(source).encode())


def test_adjusted_ratio_is_not_raw_price_change_or_dividend_added_twice():
    output = normalize_monthly_prices(payload(), record())
    assert output.adjusted_close_change_1m.iloc[2] == 0
    assert output.close.iloc[2] / output.close.iloc[1] - 1 == -0.5
    assert output.dividend_amount.iloc[2] == 1
    assert output.forward_adjusted_close_change_1m.iloc[1] == 0
    assert output.adjusted_close_change_1m.iloc[4] == pytest.approx(0.05)
    assert output.forward_end_date.iloc[3] == pd.Timestamp("2020-03-31")
    assert output.available_at.isna().all() and output.asset_id.isna().all() and output.currency.isna().all()
    assert output.adjusted_close_text.iloc[4] == "12.6"


def test_partial_current_source_month_never_produces_a_completed_month_label():
    frame = normalize_monthly_prices(payload(), record())
    assert frame.closed_month_confirmed_by_later_source_month.tolist() == [True] * 5 + [False]
    assert pd.isna(frame.adjusted_close_change_1m.iloc[-1])
    assert frame.forward_adjusted_close_change_1m.iloc[-2:].isna().all()
    # An old latest source month is still unconfirmed until a later source
    # month arrives; a newer retrieval timestamp alone cannot confirm it.
    later = normalize_monthly_prices(payload(), record(NOW + timedelta(days=40)))
    np.testing.assert_allclose(frame.adjusted_close_change_1m, later.adjusted_close_change_1m, equal_nan=True)
    assert later.source_staleness_calendar_days.iloc[0] == 41


def test_missing_month_does_not_become_a_one_month_return():
    source = payload()
    del source[SERIES]["2020-01-31"]
    frame = normalize_monthly_prices(source, record())
    assert pd.isna(frame.adjusted_close_change_1m.iloc[2])
    assert pd.isna(frame.forward_adjusted_close_change_1m.iloc[1])
    assert frame.adjusted_close_change_1m.iloc[3] == pytest.approx(0.05)


def test_market_timezone_prevents_utc_midnight_from_confirming_a_future_local_date():
    source = payload()
    del source[SERIES][DATES[-1]]
    source["Meta Data"]["3. Last Refreshed"] = "2020-03-31"
    frame = normalize_monthly_prices(source, record(pd.Timestamp("2020-04-01T01:00Z")))
    assert not frame.closed_month_confirmed_by_later_source_month.iloc[-1]
    source["Meta Data"]["3. Last Refreshed"] = "2020-04-01"
    with pytest.raises(ValueError, match="future-refreshed"):
        normalize_monthly_prices(source, record(pd.Timestamp("2020-04-01T01:00Z")))


@pytest.mark.parametrize(
    "issue",
    [
        "symbol",
        "timezone",
        "future_date",
        "refresh_disagreement",
        "duplicate_month",
        "missing_field",
        "bad_date",
        "notice",
        "empty",
    ],
)
def test_bad_source_contracts_are_rejected(issue):
    source = payload()
    if issue == "symbol":
        source["Meta Data"]["2. Symbol"] = "OTHER"
    if issue == "timezone":
        source["Meta Data"]["4. Time Zone"] = "not/a/zone"
    if issue == "future_date":
        source[SERIES]["2020-04-17"] = source[SERIES].pop(DATES[-1])
    if issue == "refresh_disagreement":
        source["Meta Data"]["3. Last Refreshed"] = "2020-04-16"
    if issue == "duplicate_month":
        source[SERIES]["2020-04-14"] = deepcopy(source[SERIES][DATES[-1]])
    if issue == "missing_field":
        del source[SERIES][DATES[0]]["5. adjusted close"]
    if issue == "bad_date":
        source[SERIES]["2019-11-29T00:00Z"] = source[SERIES].pop(DATES[0])
    if issue == "notice":
        source = {"Information": "Not a price dataset"}
    if issue == "empty":
        source[SERIES] = {}
    with pytest.raises(ValueError):
        normalize_monthly_prices(source, record())


@pytest.mark.parametrize(
    "field,value",
    [
        ("5. adjusted close", "NaN"),
        ("5. adjusted close", "0"),
        ("5. adjusted close", "1e9999"),
        ("5. adjusted close", "1e-9999"),
        ("6. volume", "1.5"),
        ("6. volume", "-1"),
        ("7. dividend amount", "-1"),
        ("2. high", "1"),
        ("1. open", True),
    ],
)
def test_invalid_numeric_domain_is_rejected(field, value):
    source = payload()
    source[SERIES][DATES[0]][field] = value
    with pytest.raises(ValueError):
        normalize_monthly_prices(source, record())


def test_input_order_immutability_and_future_price_mutation():
    source = payload()
    original = deepcopy(source)
    baseline = normalize_monthly_prices(source, record())
    assert source == original
    source[SERIES] = dict(reversed(list(source[SERIES].items())))
    pd.testing.assert_frame_equal(baseline, normalize_monthly_prices(source, record()))
    source[SERIES][DATES[-1]]["5. adjusted close"] = "999"
    pd.testing.assert_frame_equal(baseline.iloc[:-1], normalize_monthly_prices(source, record()).iloc[:-1])


def test_budget_rejects_entire_plan_before_calls_and_offline_cache_has_no_client(tmp_path):
    store, client = SnapshotStore(tmp_path), Client()
    with pytest.raises(ValueError, match="preflight"):
        ingest_monthly_prices(client, store, symbols=["SYNTH", "OTHER"], max_requests=1, clock=lambda: NOW)
    assert not client.calls
    first = ingest_monthly_prices(client, store, symbols=["SYNTH"], max_requests=1, clock=lambda: NOW)
    second = ingest_monthly_prices(None, store, symbols=["SYNTH"], max_requests=0, clock=lambda: NOW)
    assert first[0]["manifest"] == second[0]["manifest"] and second[0]["cache_hit"]
    assert len(client.calls) == 1


@pytest.mark.parametrize("kind", ["quota", "wrong_symbol", "duplicate_json"])
def test_failures_are_not_cached_and_do_not_retry_or_fall_back(tmp_path, kind):
    store = SnapshotStore(tmp_path)
    client = (
        Client(failure=AlphaVantageError("provider_notice_or_error"))
        if kind == "quota"
        else Client(source=payload("OTHER"))
    )
    if kind == "duplicate_json":
        body = json.dumps(payload()).replace('"6. volume": "1000"', '"6. volume": "1000", "6. volume": "2000"')
        client = Client(body=body.encode())
    with pytest.raises((ValueError, AlphaVantageError)):
        ingest_monthly_prices(client, store, symbols=["SYNTH", "NEXT"], max_requests=2, clock=lambda: NOW)
    assert len(client.calls) == 1
    assert store.latest("alpha_vantage", price_request("SYNTH")) is None


def test_public_demo_is_a_distinct_cache_and_not_user_history(tmp_path):
    store = SnapshotStore(tmp_path)
    first = ingest_monthly_prices(Client(), store, symbols=["IBM"], access_mode="public_demo", clock=lambda: NOW)
    with pytest.raises(ValueError, match="preflight"):
        ingest_monthly_prices(None, store, symbols=["IBM"], clock=lambda: NOW)
    table = first[0]["manifest"]["tables"]["monthly_prices"]
    frame = pd.read_parquet(store.root / table["path"], use_threads=False, pre_buffer=False)
    assert frame.sample_status.eq("public_provider_example").all()
    with pytest.raises(ValueError, match="IBM-only"):
        price_request("OTHER", "public_demo")
    client = Client()
    client.api_key = "demo"
    with pytest.raises(ValueError, match="explicit public-demo"):
        ingest_monthly_prices(client, store, symbols=["IBM"], clock=lambda: NOW)


def test_documented_public_demo_request_works_through_the_rest_adapter(tmp_path):
    class Response:
        status_code = 200

        def __init__(self, source):
            self.source = source
            self.content = json.dumps(source).encode()

        def json(self):
            return self.source

    class DocumentedExampleSession:
        def get(self, url, *, params, **kwargs):
            # Exercise the published example's function, symbol, apikey URL
            # order through REST and staging; all financial values are synthetic.
            if list(params) != ["function", "symbol", "apikey"]:
                return Response({"Information": "Public example request not recognized"})
            assert params["function"] == FUNCTION and params["symbol"] == "IBM"
            return Response(payload("IBM"))

    client = AlphaVantageRESTClient("demo")
    client.session = DocumentedExampleSession()
    result = ingest_monthly_prices(
        client, SnapshotStore(tmp_path), symbols=["IBM"], access_mode="public_demo", clock=lambda: NOW
    )
    assert result[0]["manifest"]["tables"]["monthly_prices"]["rows"] == 6


@pytest.mark.parametrize("target", ["raw", "normalized"])
def test_exact_pinned_replay_detects_corruption_without_network(tmp_path, monkeypatch, target):
    import requests

    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: pytest.fail("Replay attempted network"))
    store = SnapshotStore(tmp_path)
    capture = store.capture("alpha_vantage", price_request("SYNTH"), json.dumps(payload()).encode(), observed_at=NOW)
    result = replay_monthly_prices(store, capture)
    assert result == replay_monthly_prices(store, store.get(capture["id"]))
    path = capture["raw_path"] if target == "raw" else result["tables"]["monthly_prices"]["path"]
    (store.root / path).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        replay_monthly_prices(store, capture)


def test_observation_metadata_and_source_mode_are_bound_to_replay_identity(tmp_path):
    store = SnapshotStore(tmp_path)
    capture = store.capture(
        "alpha_vantage", price_request("IBM", "public_demo"), json.dumps(payload("IBM")).encode(), observed_at=NOW
    )
    original = replay_monthly_prices(store, capture)
    changed = {**capture, "observed_at": (NOW + timedelta(days=1)).isoformat()}
    with pytest.raises(ValueError, match="metadata differs"):
        replay_monthly_prices(store, changed)
    newer = store.capture(
        "alpha_vantage",
        price_request("IBM", "public_demo"),
        json.dumps(payload("IBM")).encode(),
        observed_at=NOW + timedelta(days=1),
    )
    assert replay_monthly_prices(store, newer)["normalizer"] != original["normalizer"]
    wrong = {**capture, "provider": "other"}
    with pytest.raises(ValueError, match="metadata differs"):
        replay_monthly_prices(store, wrong)
