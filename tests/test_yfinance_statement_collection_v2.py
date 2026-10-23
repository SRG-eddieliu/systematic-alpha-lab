"""Synthetic statement availability; real SDK integration also intercepts every dispatch."""
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline import yfinance_collection as v1
from systematic_alpha_lab.data_pipeline import yfinance_statement_collection_v2 as v2


class Clock:
    def __init__(self):
        self.tick = 0.0

    def __call__(self):
        return self.tick

    def sleep(self, seconds):
        self.tick += seconds


def financial_url(symbol, metric):
    return (f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
            f"?symbol={symbol}&type={metric}&period1=1&period2=2")


def financial_body(symbol, metric):
    return json.dumps({"timeseries": {"result": [{"meta": {"symbol": [symbol], "type": [metric]},
        "timestamp": [1767139200], metric: [{"asOfDate": "2025-12-31", "periodType": "12M" if metric.startswith(
            "annual") else "3M", "reportedValue": {"raw": 123}}]}], "error": None}}).encode()


def response(body, status=200):
    return SimpleNamespace(content=body, status_code=status)


def success(_method, target, _kwargs):
    if target == "https://fc.yahoo.com":
        return response(b"opaqueCookieBody", 404)
    if "getcrumb" in target:
        return response(b"opaqueCrumbValue")
    parsed = urlsplit(target)
    symbol = parsed.path.rsplit("/", 1)[1]
    metric = parse_qs(parsed.query)["type"][0]
    return response(financial_body(symbol, metric))


def session_factory(handler=success):
    clock, sessions = Clock(), []

    class Base:
        def __init__(self, **kwargs):
            self.options, self.calls, self.closed = kwargs, [], False
            self.retry = SimpleNamespace(count=kwargs["retry"])

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def request(self, method, url, **kwargs):
            self.calls.append({"method": method, "kwargs": kwargs, "tick": clock()})
            return handler(method, url, kwargs)

        def close(self):
            self.closed = True

    def factory(symbols, **kwargs):
        session = v1.make_bounded_yfinance_session(
            symbols, session_class=Base, monotonic=clock, sleep=clock.sleep, **kwargs,
        )
        sessions.append(session)
        return session

    return factory, sessions


def fake_sdk(*, auth=False, swallow=False, cached=False, fail_after_raw=False, wrong_quarterly_prefix=False):
    calls, constructors, locations = [], [], []

    class Ticker:
        def __init__(self, symbol, session):
            self.symbol, self.session = symbol, session
            constructors.append(symbol)

        def getter(self, method, metric, kwargs):
            calls.append({"symbol": self.symbol, "method": method, **kwargs})
            if cached:
                return pd.DataFrame([[123.]])
            if auth and len(calls) == 1:
                self.session.get("https://fc.yahoo.com")
                self.session.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
            prefix = "annual" if kwargs["freq"] == "yearly" or wrong_quarterly_prefix else "quarterly"
            for _ in range(3 if swallow else 1):
                try:
                    self.session.get(financial_url(self.symbol, prefix + metric))
                except Exception:  # Deliberately emulate the SDK swallowing transport failures.
                    if not swallow:
                        raise
            if fail_after_raw:
                raise ValueError("SECRET full URL and provider exception must never be retained")
            return pd.DataFrame([[123.]], index=[metric], columns=[pd.Timestamp("2025-12-31")])

        def get_income_stmt(self, **kwargs):
            return self.getter("get_income_stmt", "Revenue", kwargs)

        def get_balance_sheet(self, **kwargs):
            return self.getter("get_balance_sheet", "Assets", kwargs)

        def get_cash_flow(self, **kwargs):
            return self.getter("get_cash_flow", "Cash", kwargs)

    sdk = SimpleNamespace(__version__="1.7.0", Ticker=Ticker,
        config=SimpleNamespace(network=SimpleNamespace(retries=7),
                               debug=SimpleNamespace(hide_exceptions=True, logging=True)),
        const=SimpleNamespace(fundamentals_keys={"financials": ["Revenue"], "balance-sheet": ["Assets"],
                                               "cash-flow": ["Cash"]}), set_tz_cache_location=locations.append)
    return sdk, calls, constructors, locations


def collect(*, sdk=None, factory=None, **kwargs):
    sdk = sdk or fake_sdk()[0]
    factory = factory or session_factory()[0]
    return v2.collect_statement_availability(["BXP", "DOC"], sdk=sdk, session_factory=factory, **kwargs)


def test_fixed_twelve_getters_share_one_budget_and_keep_frequency_identity():
    sdk, calls, constructors, locations = fake_sdk(auth=True)
    factory, sessions = session_factory()
    result = collect(sdk=sdk, factory=factory)
    assert not result["stopped"]
    assert len(result["planned_jobs"]) == len(result["logical_attempts"]) == len(result["results"]) == 12
    assert len(result["http_captures"]) == 12 and result["session_request_count"] == 14
    assert len(sessions) == 1 and sessions[0].closed and constructors == ["BXP", "DOC"]
    assert len(locations) == 1 and not Path(locations[0]).exists()
    assert len({job["job_id"] for job in result["planned_jobs"]}) == 12
    assert [job["frequency"] for job in result["planned_jobs"]] == ["yearly"] * 6 + ["quarterly"] * 6
    for group in (result["results"], result["logical_attempts"], result["http_captures"],
                  result["request_observations"]):
        assert all(item["job_id"] == f'{item["symbol"]}:{item["statement"]}:{item["frequency"]}' for item in group)
    for item in result["http_captures"]:
        prefix = "annual" if item["frequency"] == "yearly" else "quarterly"
        assert json.loads(item["body"])["timeseries"]["result"][0]["meta"]["type"][0].startswith(prefix)
        assert hashlib.sha256(item["body"]).hexdigest() == item["sha256"]
    assert len(calls) == 12 and all(call["as_dict"] is False and call["pretty"] is False for call in calls)
    assert all(call["kwargs"]["allow_redirects"] is False and call["kwargs"]["max_redirects"] == 0
               for call in sessions[0].calls)
    assert sessions[0].options["retry"] == 0 and sdk.config.network.retries == 7
    assert result["candidate_only"] and not result["av_inputs_overwritten"]
    assert result["transport_source_sha256"] == v2.TRANSPORT_SOURCE_SHA256
    assert result["max_session_requests"] == 32 and result["maximum_automatic_retries"] == 0
    assert result["sdk_fundamentals_source_sha256"] is None


@pytest.mark.parametrize("symbols", [[], ["BXP"], ["DOC", "DOC"], ["BXP", "AAA"], ["BXP", "DOC", "AAA"]])
def test_other_symbol_plans_rejected_before_optional_sdk_import(symbols):
    with pytest.raises(ValueError):
        v2.collect_statement_availability(symbols)


@pytest.mark.parametrize("budget", [0, 33, True, 1.5])
def test_budget_is_at_most_32(budget):
    with pytest.raises(ValueError):
        v2.collect_statement_availability(["BXP", "DOC"], max_session_requests=budget)


def test_frozen_transport_source_guard_rejects_drift_before_factory(monkeypatch):
    monkeypatch.setattr(v2, "TRANSPORT_SOURCE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="Frozen transport source changed"):
        collect(factory=lambda *_a, **_kw: pytest.fail("must not construct a session"))


def test_auth_dispatches_consume_same_budget_and_swallowed_error_halts_plan():
    sdk, calls, _, _ = fake_sdk(auth=True, swallow=True)
    factory, sessions = session_factory()
    result = collect(sdk=sdk, factory=factory, max_session_requests=2)
    assert result["session_request_count"] == len(sessions[0].calls) == 2
    assert result["stop_reason"] == "session_request_budget" and not result["results"]
    assert len(calls) == len(result["logical_attempts"]) == 1
    assert [job["status"] for job in result["planned_jobs"]] == ["rejected"] + ["not_attempted"] * 11


@pytest.mark.parametrize("status,reason", [(401, "authentication_rejected"), (403, "authentication_rejected"),
    (429, "rate_limit"), (500, "financial_http_error"), (302, "redirect_rejected")])
def test_inherited_fail_closed_transport_never_dispatches_fallback(status, reason):
    sdk, calls, _, _ = fake_sdk(swallow=True)
    factory, sessions = session_factory(lambda *_: response(b"SECRET auth/HTML/error body", status))
    result = collect(sdk=sdk, factory=factory)
    assert result["session_request_count"] == len(sessions[0].calls) == len(calls) == 1
    assert result["stop_reason"] == reason and not result["results"]
    assert not result["http_captures"] and not result["financial_diagnostic_captures"]
    assert "SECRET" not in repr(result)


def test_quarterly_response_prefix_must_match_actual_request():
    def handler(method, target, kwargs):
        if "type=quarterlyRevenue" in target:
            return response(financial_body("BXP", "annualRevenue"))
        return success(method, target, kwargs)

    factory, sessions = session_factory(handler)
    result = collect(factory=factory)
    assert len(result["results"]) == len(result["http_captures"]) == 6
    assert result["session_request_count"] == len(sessions[0].calls) == 7
    assert result["stop_reason"] == "financial_identity"
    diagnostic, = result["financial_diagnostic_captures"]
    assert diagnostic["frequency"] == "quarterly" and diagnostic["job_id"] == "BXP:income:quarterly"
    assert [job["status"] for job in result["planned_jobs"]] == ["captured"] * 6 + ["rejected"] + ["not_attempted"] * 5


def test_quarterly_getter_cannot_dispatch_annual_request():
    sdk, calls, _, _ = fake_sdk(wrong_quarterly_prefix=True)
    factory, sessions = session_factory()
    result = collect(sdk=sdk, factory=factory)
    assert result["stop_reason"] == "financial_plan_rejected"
    assert len(calls) == 7 and result["session_request_count"] == len(sessions[0].calls) == 6
    assert len(result["results"]) == 6


def test_empty_json_diagnostic_retains_exact_body_and_job_identity():
    factory, _ = session_factory(lambda *_: response(b"{}"))
    result = collect(factory=factory)
    item, = result["financial_diagnostic_captures"]
    assert item["body"] == b"{}" and item["job_id"] == "BXP:income:yearly"
    assert item["frequency"] == "yearly" and result["stop_reason"] == "financial_schema"
    assert len(result["planned_jobs"]) == 12 and len(result["logical_attempts"]) == 1


def test_known_opaque_auth_echo_still_withholds_body():
    sdk, _, _, _ = fake_sdk(auth=True)

    def handler(method, target, kwargs):
        if "timeseries/" in target:
            return response(b'{"error":{"detail":"opaqueCrumbValue"}}')
        return success(method, target, kwargs)

    factory, _ = session_factory(handler)
    result = collect(sdk=sdk, factory=factory)
    assert result["stop_reason"] == "credential_fields_withheld" and result["session_request_count"] == 3
    assert not result["http_captures"] and not result["financial_diagnostic_captures"]
    assert "opaqueCrumbValue" not in repr(result)


def test_raw_survives_sdk_error_and_cached_frame_without_raw_is_rejected():
    result = collect(sdk=fake_sdk(fail_after_raw=True)[0])
    assert len(result["http_captures"]) == 1 and not result["results"]
    assert result["stop_reason"] == "sdk_getter_error" and "SECRET" not in repr(result)
    cached = collect(sdk=fake_sdk(cached=True)[0])
    assert cached["stop_reason"] == "missing_same_call_financial_capture"
    assert not cached["results"] and cached["session_request_count"] == 0


def test_transport_exception_is_counted_once_and_later_jobs_stay_not_attempted():
    def fail(*_):
        raise TimeoutError("SECRET provider URL with auth query")

    factory, sessions = session_factory(fail)
    sdk, calls, _, _ = fake_sdk(swallow=True)
    result = collect(sdk=sdk, factory=factory)
    assert result["stop_reason"] == "transport_error" and result["session_request_count"] == 1
    assert len(calls) == len(sessions[0].calls) == 1 and "SECRET" not in repr(result)


def test_real_pinned_sdk_twelve_getters_are_fully_mocked_and_caches_remain_private(monkeypatch):
    sdk = pytest.importorskip("yfinance")
    if sdk.__version__ != "1.7.0":
        pytest.skip("Only the explicitly pinned optional runtime is supported")
    curl = pytest.importorskip("curl_cffi.requests")
    data, cache = importlib.import_module("yfinance.data"), importlib.import_module("yfinance.cache")
    monkeypatch.setattr(data.SingletonMeta, "_instances", {})
    for name in ("_TzDBManager", "_CookieDBManager", "_ISINDBManager"):
        manager = getattr(cache, name)
        monkeypatch.setattr(manager, "_db", None)
        monkeypatch.setattr(manager, "_cache_dir", manager._cache_dir)
    for name, attr in (("_TzCacheManager", "_tz_cache"), ("_CookieCacheManager", "_Cookie_cache"),
                       ("_ISINCacheManager", "_isin_cache")):
        monkeypatch.setattr(getattr(cache, name), attr, None)
    monkeypatch.setattr(data.YfData, "_get_cookie_and_crumb", lambda *_a, **_kw: ("test-only", "basic"))
    dispatches, sessions, clock = [], [], Clock()

    def dispatch(_self, method, target, **kwargs):
        dispatches.append((method, kwargs))
        parsed = urlsplit(target)
        symbol, metrics = parsed.path.rsplit("/", 1)[1], parse_qs(parsed.query)["type"][0].split(",")
        payload = json.loads(financial_body(symbol, metrics[0]))
        payload["timeseries"]["result"].append({"meta": {"symbol": [symbol], "type": [metrics[1]]},
                                                "timestamp": [1767139200]})
        body = json.dumps(payload).encode()
        return SimpleNamespace(content=body, text=body.decode(), status_code=200, url=target)

    monkeypatch.setattr(curl.Session, "request", dispatch)

    def factory(symbols, **kwargs):
        session = v1.make_bounded_yfinance_session(symbols, monotonic=clock, sleep=clock.sleep, **kwargs)
        assert isinstance(session, curl.Session)
        sessions.append(session)
        return session

    try:
        result = v2.collect_statement_availability(["BXP", "DOC"], session_factory=factory)
        assert not result["stopped"], result["stop_reason"]
        assert len(result["results"]) == len(result["http_captures"]) == len(dispatches) == 12
        assert result["sdk_fundamentals_source_sha256"] == v2.SDK_FUNDAMENTALS_SOURCE_SHA256
        assert all(not item["frame"].empty for item in result["results"])
        assert [item["frequency"] for item in result["results"]] == ["yearly"] * 6 + ["quarterly"] * 6
        locations = {getattr(cache, name)._cache_dir for name in (
            "_TzDBManager", "_CookieDBManager", "_ISINDBManager")}
        assert len(locations) == 1 and not Path(next(iter(locations))).exists()
        with pytest.raises(ValueError, match="fresh dedicated process"):
            v2.collect_statement_availability(["BXP", "DOC"], session_factory=factory)
        assert len(sessions) == 1
    finally:
        data.YfData.cache_get.cache_clear()
