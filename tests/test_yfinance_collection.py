"""No provider calls: exercise the transport hook and swallowed SDK failures."""
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from systematic_alpha_lab.data_pipeline.yfinance_collection import (
    CollectionBlocked,
    collect_yearly_statements,
    make_bounded_yfinance_session,
)


class Clock:
    def __init__(self):
        self.tick = 0.0
        self.sleeps = []

    def __call__(self):
        return self.tick

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.tick += seconds


def financial_body(symbol="AAA", metric="annualRevenue"):
    return json.dumps({"timeseries": {"result": [{"meta": {"symbol": [symbol], "type": [metric]},
                       "timestamp": [int(pd.Timestamp("2025-12-31", tz="UTC").timestamp())],
                       metric: [{"asOfDate": "2025-12-31", "reportedValue": {"raw": 123}}]}],
                       "error": None}}).encode()


def url(symbol="AAA", metric="annualRevenue"):
    return (f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}"
            f"?symbol={symbol}&type={metric}&period1=1&period2=2")


def response(body, status=200):
    return SimpleNamespace(content=body, status_code=status)


def transport(handler, *, budget=40, interval=2, symbols=("AAA",), clock=None):
    clock = clock or Clock()

    class Base:
        def __init__(self, **kwargs):
            self.init_kwargs, self.calls, self.closed = kwargs, [], False
            self.retry = SimpleNamespace(count=kwargs["retry"])

        def request(self, method, target, **kwargs):
            self.calls.append({"method": method, "url": target, "kwargs": kwargs, "tick": clock()})
            return handler(method, target, kwargs)

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def close(self):
            self.closed = True

    session = make_bounded_yfinance_session(
        symbols, max_session_requests=budget, min_interval_seconds=interval,
        session_class=Base, monotonic=clock, sleep=clock.sleep, now=lambda: "2026-10-23T10:00:00Z",
    )
    return session, clock


def begin(session, symbol="AAA", statement="income", metric="Revenue"):
    session.begin_logical(symbol, statement, [metric])


def fake_sdk(*, auth=False, mode="normal"):
    calls, cache_locations = [], []

    class Ticker:
        def __init__(self, symbol, session):
            self.symbol, self.session = symbol, session

        def _getter(self, name, metric, kwargs):
            calls.append((self.symbol, name, kwargs))
            if mode == "cache_only":
                return pd.DataFrame([[1.]])
            if auth and len(calls) == 1:
                self.session.get("https://fc.yahoo.com")
                self.session.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
            if mode == "swallow":
                for _ in range(3):
                    try:
                        self.session.get(url(self.symbol, metric))
                    except Exception:  # noqa: BLE001, S112 - deliberately emulate the SDK swallowing all failures.
                        continue
            else:
                self.session.get(url(self.symbol, metric))
            if mode == "raise_after_raw":
                raise ValueError("SECRET_COOKIE full provider URL should not appear")
            return pd.DataFrame([[123.]], index=[metric.removeprefix("annual")],
                                columns=[pd.Timestamp("2025-12-31")])

        def get_income_stmt(self, **kwargs):
            return self._getter("get_income_stmt", "annualRevenue", kwargs)

        def get_balance_sheet(self, **kwargs):
            return self._getter("get_balance_sheet", "annualAssets", kwargs)

        def get_cash_flow(self, **kwargs):
            return self._getter("get_cash_flow", "annualCash", kwargs)

    sdk = SimpleNamespace(
        __version__="1.7.0", Ticker=Ticker,
        config=SimpleNamespace(network=SimpleNamespace(retries=9),
                               debug=SimpleNamespace(hide_exceptions=True, logging=True)),
        const=SimpleNamespace(fundamentals_keys={"financials": ["Revenue"], "balance-sheet": ["Assets"],
                                               "cash-flow": ["Cash"]}),
        set_tz_cache_location=cache_locations.append,
    )
    return sdk, calls, cache_locations


def successful_handler(_, target, __):
    if target == "https://fc.yahoo.com":
        return response(b"COOKIE_SECRET", 404)
    if "getcrumb" in target:
        return response(b"CRUMB_SECRET")
    symbol = target.rsplit("timeseries/", 1)[1].split("?")[0]
    metric = target.split("type=")[1].split("&")[0]
    return response(financial_body(symbol, metric))


def collect(session, sdk, **kwargs):
    return collect_yearly_statements(["AAA"], sdk=sdk, session_factory=lambda *a, **k: session, **kwargs)


def test_nine_explicit_getters_and_same_call_raw_are_retained():
    session, _ = transport(successful_handler, symbols=("AAA", "BBB", "CCC"))
    sdk, calls, locations = fake_sdk(auth=True)
    result = collect_yearly_statements(["AAA", "BBB", "CCC"], sdk=sdk, session_factory=lambda *a, **k: session)
    assert len(calls) == len(result["results"]) == len(result["http_captures"]) == 9
    assert len(result["logical_attempts"]) == 9
    assert result["session_request_count"] == 11
    assert result["stopped"] is False
    assert {item["statement"] for item in result["results"]} == {"income", "balance-sheet", "cash-flow"}
    assert all(kwargs == {"as_dict": False, "pretty": False, "freq": "yearly"} for _, _, kwargs in calls)
    assert all(item["yfinance_version"] == "1.7.0" for item in result["results"])
    assert sdk.config.network.retries == 9 and sdk.config.debug.logging is True
    assert len(locations) == 1 and not Path(locations[0]).exists()
    assert session.closed
    assert session.init_kwargs == {"impersonate": "chrome", "retry": 0, "allow_redirects": False,
                                   "max_redirects": 0, "debug": False}
    assert all(call["kwargs"]["allow_redirects"] is False and call["kwargs"]["max_redirects"] == 0
               for call in session.calls)
    assert "COOKIE_SECRET" not in repr(result) and "CRUMB_SECRET" not in repr(result)


@pytest.mark.parametrize("symbols", [[], ["AAA"] * 2, ["AAA", "BBB", "CCC", "DDD"], ["aaa"], ["A/BB"]])
def test_invalid_plan_rejected_before_sdk_or_session(symbols):
    with pytest.raises(ValueError):
        collect_yearly_statements(symbols)


@pytest.mark.parametrize("budget", [0, -1, 41, True, 1.5])
def test_invalid_dispatch_budget(budget):
    with pytest.raises(ValueError):
        make_bounded_yfinance_session(["AAA"], max_session_requests=budget)


@pytest.mark.parametrize("interval", [0, .5, True, float("nan"), float("inf")])
def test_invalid_interval(interval):
    with pytest.raises(ValueError):
        make_bounded_yfinance_session(["AAA"], min_interval_seconds=interval)


def test_cap_includes_auth_and_survives_sdk_swallowing_budget_errors():
    session, _ = transport(successful_handler, budget=2)
    sdk, calls, _ = fake_sdk(auth=True, mode="swallow")
    result = collect(session, sdk)
    assert result["session_request_count"] == len(session.calls) == 2
    assert result["stop_reason"] == "session_request_budget"
    assert len(calls) == len(result["logical_attempts"]) == 1
    assert not result["results"]


@pytest.mark.parametrize("status,reason", [(401, "authentication_rejected"), (403, "authentication_rejected"),
                                          (429, "rate_limit"), (500, "financial_http_error"),
                                          (302, "redirect_rejected")])
def test_first_financial_http_failure_blocks_internal_fallback(status, reason):
    session, _ = transport(lambda *_: response(b"SECRET response", status))
    sdk, calls, _ = fake_sdk(mode="swallow")
    result = collect(session, sdk)
    assert result["stop_reason"] == reason
    assert len(calls) == len(session.calls) == result["session_request_count"] == 1
    assert not result["http_captures"] and not result["financial_diagnostic_captures"]
    assert result["request_observations"][0]["body_capture_status"] == "withheld"
    assert "SECRET response" not in repr(result)


def test_transport_failure_is_counted_and_never_repeated():
    def fail(*_):
        raise TimeoutError("https://SECRET_URL?crumb=SECRET_CRUMB")

    session, _ = transport(fail)
    sdk, calls, _ = fake_sdk(mode="swallow")
    result = collect(session, sdk)
    assert result["session_request_count"] == len(session.calls) == len(calls) == 1
    assert result["stop_reason"] == "transport_error"
    assert "SECRET" not in repr(result)


@pytest.mark.parametrize("target", [url("BBB"), url(metric="quarterlyRevenue"), url(metric="annualAssets"),
                                     "https://query2.finance.yahoo.com/v10/finance/quoteSummary/AAA",
                                     "https://example.com/", url().replace("https://", "http://")])
def test_outside_plan_routes_and_fields_rejected_before_dispatch(target):
    session, _ = transport(successful_handler)
    begin(session)
    with pytest.raises(CollectionBlocked):
        session.get(target)
    assert session.session_request_count == 0 and not session.calls


def test_auth_route_may_dispatch_once_and_body_always_withheld():
    session, _ = transport(successful_handler)
    begin(session)
    session.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
    with pytest.raises(CollectionBlocked, match="automatic_auth_retry_rejected"):
        session.get("https://query2.finance.yahoo.com/v1/test/getcrumb")
    assert len(session.calls) == 1
    assert session.request_observations[0]["safe_reason"] == "authentication_body_withheld"
    assert not session.http_captures and not session.financial_diagnostic_captures


def test_slow_response_still_has_full_completion_to_next_dispatch_delay():
    clock = Clock()

    def slow(*_):
        clock.tick += 11
        return response(financial_body())

    session, _ = transport(slow, clock=clock)
    begin(session)
    session.get(url())
    session.get(url())
    assert [item["tick"] for item in session.calls] == [0, 13]
    assert clock.sleeps == [2]


def test_clock_rollback_fails_before_another_dispatch():
    session, clock = transport(successful_handler)
    begin(session)
    session.get(url())
    clock.tick = -1
    with pytest.raises(CollectionBlocked, match="clock_rollback"):
        session.get(url())
    assert len(session.calls) == 1


@pytest.mark.parametrize("body,reason", [(b"{}", "financial_schema"),
    (b'{"timeseries":{"result":[],"error":null}}', "financial_empty_result"),
    (b'{"timeseries":{"result":[],"error":{"code":"Not Found"}}}', "financial_provider_error"),
    (financial_body("BBB"), "financial_identity"), (financial_body(metric="annualAssets"), "financial_identity")])
def test_safe_financial_json_diagnostics_preserve_exact_body(body, reason):
    session, _ = transport(lambda *_: response(body))
    sdk, calls, _ = fake_sdk(mode="swallow")
    result = collect(session, sdk)
    assert result["stop_reason"] == reason and len(calls) == len(session.calls) == 1
    assert not result["http_captures"] and not result["results"]
    capture, = result["financial_diagnostic_captures"]
    assert capture["body"] == body and capture["length"] == len(body)
    assert capture["sha256"] == hashlib.sha256(body).hexdigest()
    assert capture["symbol"] == "AAA" and capture["statement"] == "income"
    assert capture["safe_reason"] == reason and capture["status"] == 200


def test_meta_only_metric_keeps_other_same_response_observations_and_exact_raw():
    payload = json.loads(financial_body())
    payload["timeseries"]["result"].append({"meta": {"symbol": ["AAA"], "type": ["annualMissing"]},
                                              "timestamp": [1767139200]})
    body = json.dumps(payload).encode()
    session, _ = transport(lambda *_: response(body))
    session.begin_logical("AAA", "income", ["Revenue", "Missing"])
    session.get(url(metric="annualRevenue,annualMissing"))
    assert not session.blocked and not session.financial_diagnostic_captures
    capture, = session.http_captures
    assert capture["body"] == body and capture["sha256"] == hashlib.sha256(body).hexdigest()
    assert json.loads(capture["body"])["timeseries"]["result"][0]["annualRevenue"][0]["reportedValue"]["raw"] == 123


@pytest.mark.parametrize("value", [None, {}, "missing", 0])
def test_present_nonlist_metric_remains_a_rejected_financial_schema(value):
    payload = json.loads(financial_body())
    payload["timeseries"]["result"][0]["annualRevenue"] = value
    body = json.dumps(payload).encode()
    session, _ = transport(lambda *_: response(body))
    begin(session)
    with pytest.raises(CollectionBlocked, match="financial_schema"):
        session.get(url())
    assert not session.http_captures
    assert session.financial_diagnostic_captures[0]["body"] == body


@pytest.mark.parametrize("body,reason", [(b"<html>SECRET</html>", "financial_json_unparseable"),
    (b'{"crumb":"SECRET"}', "credential_fields_withheld"),
    (b'{"nested":{"access_token":"SECRET"}}', "credential_fields_withheld"),
    (b'{"error":"cookie=SECRET"}', "credential_fields_withheld"),
    (b'{"duplicate":1,"duplicate":2}', "financial_json_unparseable")])
def test_unparseable_or_credentials_never_saved(body, reason):
    session, _ = transport(lambda *_: response(body))
    sdk, _, _ = fake_sdk()
    result = collect(session, sdk)
    assert result["stop_reason"] == reason
    assert not result["http_captures"] and not result["financial_diagnostic_captures"]
    assert "SECRET" not in repr(result)


def test_valid_raw_survives_sdk_dataframe_failure():
    session, _ = transport(successful_handler)
    sdk, calls, _ = fake_sdk(mode="raise_after_raw")
    result = collect(session, sdk)
    assert len(result["http_captures"]) == len(calls) == 1
    assert not result["results"] and result["stop_reason"] == "sdk_getter_error"
    assert "SECRET" not in repr(result)


def test_cached_dataframe_without_same_call_raw_is_rejected():
    session, _ = transport(successful_handler)
    sdk, calls, _ = fake_sdk(mode="cache_only")
    result = collect(session, sdk)
    assert not result["results"] and not result["http_captures"]
    assert result["session_request_count"] == 0 and len(calls) == 1
    assert result["logical_attempts"][0]["status"] == "rejected"
    assert result["stop_reason"] == "missing_same_call_financial_capture"


def test_partial_results_are_retained_on_later_failure():
    count = 0

    def handler(*args):
        nonlocal count
        count += 1
        return successful_handler(*args) if count == 1 else response(b"{}")

    session, _ = transport(handler)
    sdk, calls, _ = fake_sdk()
    result = collect(session, sdk)
    assert len(result["results"]) == len(result["http_captures"]) == 1
    assert len(result["financial_diagnostic_captures"]) == 1
    assert len(calls) == len(result["logical_attempts"]) == 2


@pytest.mark.parametrize("source", ["crumb_response", "request_param", "cookie"])
def test_bare_opaque_auth_values_in_financial_json_are_withheld(source):
    secret = "opaqueAuthValue-12345"

    def handler(_method, target, _kwargs):
        if "getcrumb" in target:
            return response(secret.encode())
        return response(json.dumps({"error": {"detail": secret}}).encode())

    session, _ = transport(handler)
    begin(session)
    kwargs = {}
    if source == "crumb_response":
        session.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
    elif source == "request_param":
        kwargs["params"] = {"crumb": secret}
    else:
        session.cookies = {"A": secret}
    with pytest.raises(CollectionBlocked, match="credential_fields_withheld"):
        session.get(url(), **kwargs)
    assert not session.http_captures and not session.financial_diagnostic_captures
    assert secret not in repr(session.request_observations)


def test_unexpected_response_processing_error_blocks_swallowed_fallback():
    session, _ = transport(lambda *_: SimpleNamespace(status_code=200))
    sdk, calls, _ = fake_sdk(mode="swallow")
    result = collect(session, sdk)
    assert result["stop_reason"] == "response_processing_error"
    assert len(session.calls) == len(calls) == 1


def test_sdk_runtime_version_pin_fails_before_factory():
    sdk, _, _ = fake_sdk()
    sdk.__version__ = "future"
    with pytest.raises(ValueError, match="pinned"):
        collect_yearly_statements(["AAA"], sdk=sdk, session_factory=lambda *_a, **_kw: pytest.fail("dispatch"))


def test_real_sdk_and_curl_hook_without_network_and_fresh_process_gate(monkeypatch):
    sdk = pytest.importorskip("yfinance")
    if sdk.__version__ != "1.7.0":
        pytest.skip("Only the explicitly pinned optional runtime is supported")
    curl = pytest.importorskip("curl_cffi.requests")
    data = importlib.import_module("yfinance.data")
    cache = importlib.import_module("yfinance.cache")
    monkeypatch.setattr(data.SingletonMeta, "_instances", {})
    for name in ("_TzDBManager", "_CookieDBManager", "_ISINDBManager"):
        manager = getattr(cache, name)
        monkeypatch.setattr(manager, "_db", None)
        monkeypatch.setattr(manager, "_cache_dir", manager._cache_dir)
    for name, attr in (("_TzCacheManager", "_tz_cache"), ("_CookieCacheManager", "_Cookie_cache"),
                       ("_ISINCacheManager", "_isin_cache")):
        monkeypatch.setattr(getattr(cache, name), attr, None)
    # Every low-level request is intercepted. Cookie/crumb bootstrap is stubbed,
    # so this test has no provider dispatch and cannot read a user cookie cache.
    monkeypatch.setattr(data.YfData, "_get_cookie_and_crumb", lambda *_a, **_kw: ("test-only", "basic"))
    dispatches = []

    def dispatch(_self, method, target, **kwargs):
        dispatches.append((method, kwargs))
        symbol = target.rsplit("timeseries/", 1)[1].split("?")[0]
        metrics = target.split("type=")[1].split("&")[0].split(",")
        payload = json.loads(financial_body(symbol, metrics[0]))
        # A declared metric with no item array is unobserved, while another
        # metric in this exact response still supplies the real SDK's frame.
        payload["timeseries"]["result"].append({"meta": {"symbol": [symbol], "type": [metrics[1]]},
                                                  "timestamp": [1767139200]})
        body = json.dumps(payload).encode()
        return SimpleNamespace(content=body, text=body.decode(), status_code=200, url=target)

    monkeypatch.setattr(curl.Session, "request", dispatch)
    clock = Clock()
    sessions = []

    def factory(symbols, **kwargs):
        session = make_bounded_yfinance_session(symbols, monotonic=clock, sleep=clock.sleep, **kwargs)
        assert isinstance(session, curl.Session)
        sessions.append(session)
        return session

    try:
        result = collect_yearly_statements(["AAA", "BBB", "CCC"], session_factory=factory)
        assert not result["stopped"], result["stop_reason"]
        assert len(result["results"]) == len(result["http_captures"]) == len(dispatches) == 9
        assert all(not item["frame"].empty for item in result["results"])
        locations = {getattr(cache, name)._cache_dir for name in (
            "_TzDBManager", "_CookieDBManager", "_ISINDBManager")}
        assert len(locations) == 1 and not Path(next(iter(locations))).exists()
        with pytest.raises(ValueError, match="fresh dedicated process"):
            collect_yearly_statements(["AAA"], session_factory=factory)
        assert len(sessions) == 1
    finally:
        data.YfData.cache_get.cache_clear()
