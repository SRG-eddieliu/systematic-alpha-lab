"""Bounded Yahoo annual candidates, with same-dispatch financial JSON captures.

The optional yfinance/curl_cffi imports happen only on explicit collection.
Counts describe Session.request dispatches, not TCP requests or wire exchanges.
Use a fresh, dedicated process: yfinance has process-global sessions and caches.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
import math
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qsl, unquote, urlsplit

import pandas as pd

YFINANCE_VERSION = "1.7.0"
METHODS = (("get_income_stmt", "income", "financials"),
           ("get_balance_sheet", "balance-sheet", "balance-sheet"),
           ("get_cash_flow", "cash-flow", "cash-flow"))
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,24}\Z")
_CREDENTIAL_KEYS = {
    "apikey", "accesskey", "authorization", "cookie", "cookies", "setcookie", "crumb", "csrftoken",
    "token", "accesstoken", "refreshtoken", "password", "passwd", "secret", "clientsecret", "sessionid",
    "privatekey", "credentials", "credential",
}


class CollectionBlocked(RuntimeError):
    """A fixed, safe reason; provider exception text is never propagated."""


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _symbols(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 3:
        raise ValueError("Declare one to three unique provider symbols")
    if any(not isinstance(value, str) or not _SYMBOL.fullmatch(value) for value in values):
        raise ValueError("Invalid explicit provider symbol")
    if len(set(values)) != len(values):
        raise ValueError("Duplicate provider symbols")
    return tuple(values)


def _positive_interval(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 1:
        raise ValueError("The completion-to-next-dispatch interval must be at least one second")
    return float(value)


def _budget(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 40:
        raise ValueError("Declare a session-dispatch budget between one and 40")
    return value


def _json_object(body):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("nonfinite_json")

    value = json.loads(body, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise TypeError("json_object_required")
    return value


def _credential_free(value):
    if isinstance(value, dict):
        return all(re.sub(r"[^a-z0-9]", "", key.lower()) not in _CREDENTIAL_KEYS and _credential_free(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return all(_credential_free(item) for item in value)
    if isinstance(value, str):
        return not re.search(r"(?i)(?:crumb|cookie|authorization|password|token|secret|sessionid)\s*[:=]", value)
    return True


def _singleton(value):
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def _financial_reason(payload, symbol, requested_types):
    envelope = payload.get("timeseries")
    if not isinstance(envelope, dict):
        return "financial_schema"
    if envelope.get("error") is not None:
        return "financial_provider_error"
    series = envelope.get("result")
    if not isinstance(series, list):
        return "financial_schema"
    if not series:
        return "financial_empty_result"
    seen = set()
    for item in series:
        if not isinstance(item, dict) or not isinstance(item.get("meta"), dict):
            return "financial_schema"
        meta = item["meta"]
        metric = _singleton(meta.get("type"))
        if _singleton(meta.get("symbol")) != symbol or not isinstance(metric, str) or metric not in requested_types:
            return "financial_identity"
        if metric in seen or set(item) - {"meta", "timestamp", metric} or (
            metric in item and not isinstance(item[metric], list)
        ):
            return "financial_schema"
        seen.add(metric)
    return None


def make_bounded_yfinance_session(symbols, *, max_session_requests=40, min_interval_seconds=2,
                                 session_class=None, monotonic=time.monotonic, sleep=time.sleep, now=_utc_now):
    """Create a curl_cffi Session subclass; injected classes are for offline tests.

    All auth routes are body-withheld and may dispatch once each. A failed
    financial dispatch blocks fallback/chunk/cookie retries, including retries
    attempted inside yfinance after it catches an exception.
    """
    plan = _symbols(symbols)
    max_session_requests = _budget(max_session_requests)
    interval = _positive_interval(min_interval_seconds)
    if session_class is None:
        session_class = importlib.import_module("curl_cffi.requests").Session

    class BoundedSession(session_class):
        def __init__(self):
            super().__init__(impersonate="chrome", retry=0, allow_redirects=False, max_redirects=0, debug=False)
            self.session_request_count = 0
            self.request_observations = []
            self.http_captures = []
            self.financial_diagnostic_captures = []
            self.blocked = False
            self.stop_reason = None
            self._job = None
            self._auth_seen = set()
            self._completed = None
            self._last_clock = None
            self._sensitive_values = set()
            self._dispatch_lock = threading.RLock()

        def block(self, reason):
            if not self.blocked:
                self.blocked, self.stop_reason = True, reason
            raise CollectionBlocked(self.stop_reason)

        def begin_logical(self, symbol, statement, metrics):
            if symbol not in plan or statement not in {item[1] for item in METHODS}:
                self.block("logical_plan_rejected")
            self._job = (symbol, statement, frozenset("annual" + metric for metric in metrics))

        def _clock(self):
            tick = monotonic()
            if not isinstance(tick, (int, float)) or not math.isfinite(tick) or (
                self._last_clock is not None and tick < self._last_clock
            ):
                self.block("clock_rollback")
            self._last_clock = tick
            return tick

        def _remember_sensitive(self, value):
            if isinstance(value, bytes):
                try:
                    value = value.decode("utf-8", errors="strict")
                except UnicodeError:
                    self.block("credential_inspection_unavailable")
            if isinstance(value, str) and value:
                self._sensitive_values.add(value)

        def _contains_sensitive(self, value):
            if isinstance(value, dict):
                return any(self._contains_sensitive(key) or self._contains_sensitive(item)
                           for key, item in value.items())
            if isinstance(value, list):
                return any(self._contains_sensitive(item) for item in value)
            return isinstance(value, str) and any(secret in value for secret in self._sensitive_values)

        def _remember_cookies(self, response):
            for cookies in (getattr(self, "cookies", None), getattr(response, "cookies", None)):
                if cookies is None:
                    continue
                jar = getattr(cookies, "jar", None)
                if jar is not None:
                    for cookie in jar:
                        self._remember_sensitive(cookie.value)
                else:
                    for value in cookies.values():
                        self._remember_sensitive(value)

        def _route(self, method, url, params):
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment or (
                parsed.port not in (None, 443)
            ):
                self.block("route_rejected")
            host, path = parsed.hostname, parsed.path
            prefix = "/ws/fundamentals-timeseries/v1/finance/timeseries/"
            if host in {"query1.finance.yahoo.com", "query2.finance.yahoo.com"} and path.startswith(prefix):
                if method != "GET" or self._job is None:
                    self.block("financial_plan_rejected")
                symbol, _, allowed_types = self._job
                if unquote(path[len(prefix):]) != symbol:
                    self.block("financial_plan_rejected")
                query = parse_qsl(parsed.query, keep_blank_values=True)
                if params:
                    query += list(params.items()) if isinstance(params, dict) else list(params)
                symbols_q = [value for key, value in query if key == "symbol"]
                types_q = [value for key, value in query if key == "type"]
                if symbols_q != [symbol] or len(types_q) != 1 or not isinstance(types_q[0], str):
                    self.block("financial_plan_rejected")
                requested = types_q[0].split(",")
                if not requested or len(set(requested)) != len(requested) or not set(requested) <= allowed_types:
                    self.block("financial_plan_rejected")
                return "financial_timeseries", frozenset(requested)
            auth = {
                ("GET", "fc.yahoo.com", "/"): "cookie",
                ("GET", "fc.yahoo.com", ""): "cookie",
                ("GET", "query1.finance.yahoo.com", "/v1/test/getcrumb"): "crumb",
                ("GET", "query2.finance.yahoo.com", "/v1/test/getcrumb"): "crumb",
                ("GET", "guce.yahoo.com", "/consent"): "consent",
                ("POST", "consent.yahoo.com", "/v2/collectConsent"): "consent_submit",
                ("GET", "guce.yahoo.com", "/copyConsent"): "consent_copy",
            }
            route = auth.get((method, host, path))
            if route is None or self._job is None:
                self.block("route_rejected")
            if route in self._auth_seen:
                self.block("automatic_auth_retry_rejected")
            return route, frozenset()

        def request(self, method, url, **kwargs):
            with self._dispatch_lock:
                return self._bounded_request(method, url, **kwargs)

        def _bounded_request(self, method, url, **kwargs):
            if self.blocked:
                raise CollectionBlocked(self.stop_reason)
            try:
                route, requested_types = self._route(str(method).upper(), url, kwargs.get("params"))
            except CollectionBlocked:
                raise
            except (TypeError, ValueError):
                self.block("route_rejected")
            if self.session_request_count >= max_session_requests:
                self.block("session_request_budget")
            tick = self._clock()
            if self._completed is not None and tick - self._completed < interval:
                sleep(interval - (tick - self._completed))
                if self._clock() - self._completed < interval:
                    self.block("interval_not_elapsed")
            kwargs.update(allow_redirects=False, max_redirects=0)
            params = kwargs.get("params") or {}
            for key, value in (params.items() if isinstance(params, dict) else params):
                if re.sub(r"[^a-z0-9]", "", key.lower()) in _CREDENTIAL_KEYS:
                    self._remember_sensitive(value)
            # curl_cffi accepts RetryStrategy via the session, not request kwargs.
            strategy = getattr(self, "retry", None)
            if strategy is not None and getattr(strategy, "count", 0) != 0:
                self.block("automatic_transport_retry_rejected")
            self.session_request_count += 1
            if route != "financial_timeseries":
                self._auth_seen.add(route)
            observation = {"sequence": self.session_request_count, "route": route,
                           "started_at": now(), "status": None, "body_capture_status": "withheld"}
            self.request_observations.append(observation)
            try:
                response = super().request(method, url, **kwargs)
            except Exception:  # noqa: BLE001 - provider exceptions must not expose URLs or auth values.
                self._completed = self._clock()
                observation.update(finished_at=now(), safe_reason="transport_error")
                self.block("transport_error")
            self._completed = self._clock()
            observation["finished_at"] = now()
            try:
                return self._capture_response(response, observation, route, requested_types)
            except CollectionBlocked:
                raise
            except Exception:  # noqa: BLE001 - unexpected response properties must also block SDK fallback.
                observation["safe_reason"] = "response_processing_error"
                self.block("response_processing_error")

        def _capture_response(self, response, observation, route, requested_types):
            status = response.status_code
            observation["status"] = status
            body = response.content
            if not isinstance(body, bytes):
                observation["safe_reason"] = "response_bytes_required"
                self.block("response_bytes_required")
            observation.update(sha256=hashlib.sha256(body).hexdigest(), length=len(body))
            self._remember_cookies(response)
            if status in (401, 403, 429):
                observation["safe_reason"] = "rate_limit" if status == 429 else "authentication_rejected"
                self.block(observation["safe_reason"])
            if 300 <= status < 400:
                observation["safe_reason"] = "redirect_rejected"
                self.block("redirect_rejected")
            if route != "financial_timeseries":
                observation["safe_reason"] = "authentication_body_withheld"
                if route == "crumb" and status == 200:
                    self._remember_sensitive(body)
                if status != 200 and not (route == "cookie" and status == 404):
                    self.block("authentication_http_error")
                return response
            if status != 200:
                observation["safe_reason"] = "financial_http_error"
                self.block("financial_http_error")
            try:
                payload = _json_object(body)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                observation["safe_reason"] = "financial_json_unparseable"
                self.block("financial_json_unparseable")
            if not _credential_free(payload) or self._contains_sensitive(payload):
                observation["safe_reason"] = "credential_fields_withheld"
                self.block("credential_fields_withheld")
            symbol, statement, _ = self._job
            capture = {name: observation[name] for name in ("sequence", "route", "status", "sha256", "length")}
            capture.update(body=body, observed_at=observation["finished_at"], symbol=symbol, statement=statement)
            reason = _financial_reason(payload, symbol, requested_types)
            if reason:
                capture["safe_reason"] = reason
                self.financial_diagnostic_captures.append(capture)
                observation.update(body_capture_status="financial_diagnostic", safe_reason=reason)
                self.block(reason)
            self.http_captures.append(capture)
            observation["body_capture_status"] = "financial_json"
            return response

    return BoundedSession()


@contextmanager
def _quiet_sdk(sdk):
    config = sdk.config
    old = (config.network.retries, config.debug.hide_exceptions, config.debug.logging)
    names = {"yfinance", "curl_cffi", *(name for name in logging.Logger.manager.loggerDict
                                        if name.startswith(("yfinance.", "curl_cffi.")))}
    loggers = [(logging.getLogger(name), logging.getLogger(name).disabled) for name in names]
    disabled_level = logging.root.manager.disable
    try:
        config.network.retries, config.debug.hide_exceptions, config.debug.logging = 0, False, False
        # Includes loggers the SDK creates later. The collector requires a dedicated process.
        logging.disable(logging.CRITICAL)
        for logger, _ in loggers:
            logger.disabled = True
        yield
    finally:
        config.network.retries, config.debug.hide_exceptions, config.debug.logging = old
        logging.disable(disabled_level)
        for logger, disabled in loggers:
            logger.disabled = disabled


@contextmanager
def _private_cache(sdk, *, real_sdk):
    """The SDK's tz setter also relocates cookie and ISIN SQLite caches in 1.7.0."""
    if real_sdk:
        data = importlib.import_module("yfinance.data")
        cache = importlib.import_module("yfinance.cache")
        managers = [getattr(cache, name) for name in ("_TzDBManager", "_CookieDBManager", "_ISINDBManager")]
        if data.SingletonMeta._instances or any(manager._db is not None for manager in managers) or any(
            getattr(cache, name).__dict__.get(attribute) is not None
            for name, attribute in (("_TzCacheManager", "_tz_cache"), ("_CookieCacheManager", "_Cookie_cache"),
                                    ("_ISINCacheManager", "_isin_cache"))
        ):
            raise ValueError("A fresh dedicated process is required before yfinance collection")
    else:
        managers = []
    with tempfile.TemporaryDirectory(prefix="yf-private-") as location:
        sdk.set_tz_cache_location(location)
        try:
            yield
        finally:
            for manager in managers:
                manager.close_db()


def collect_yearly_statements(symbols, *, max_session_requests=40, min_interval_seconds=2,
                              session_factory=None, sdk=None, now=_utc_now):
    """Call at most nine explicit annual getters, once each, without retries.

    ``results`` contains only DataFrames with same-logical-call financial JSON.
    ``logical_attempts`` also records failed getters. Valid financial JSON is
    returned even if the SDK subsequently cannot construct its DataFrame.
    Frames retain the SDK representation; they are not raw HTTP or accepted
    accounting facts. Date/issuer/accounting acceptance belongs downstream.
    """
    plan = _symbols(symbols)
    _budget(max_session_requests)
    _positive_interval(min_interval_seconds)
    real_sdk = sdk is None
    if real_sdk:
        sdk = importlib.import_module("yfinance")
    if sdk.__version__ != YFINANCE_VERSION:
        raise ValueError("The collector requires the pinned yfinance version")
    factory = session_factory or make_bounded_yfinance_session
    results, attempts = [], []
    with _quiet_sdk(sdk), _private_cache(sdk, real_sdk=real_sdk):
        session = factory(plan, max_session_requests=max_session_requests, min_interval_seconds=min_interval_seconds)
        try:
            for symbol in plan:
                try:
                    ticker = sdk.Ticker(symbol, session=session)
                except Exception:  # noqa: BLE001 - sanitize SDK errors at the collection boundary.
                    session.blocked, session.stop_reason = True, "sdk_initialization_error"
                    break
                for method, statement, key in METHODS:
                    session.begin_logical(symbol, statement, sdk.const.fundamentals_keys[key])
                    first_capture = len(session.http_captures)
                    attempt = {"symbol": symbol, "method": method, "statement": statement,
                               "started_at": now(), "yfinance_version": sdk.__version__}
                    attempts.append(attempt)
                    frame = None
                    try:
                        frame = getattr(ticker, method)(as_dict=False, pretty=False, freq="yearly")
                        if not isinstance(frame, pd.DataFrame):
                            session.block("sdk_dataframe_required")
                        if len(session.http_captures) == first_capture:
                            session.block("missing_same_call_financial_capture")
                    except Exception:  # noqa: BLE001 - the SDK can raise arbitrary provider exception types.
                        attempt.update(status="rejected", safe_error_class=(session.stop_reason or "sdk_getter_error"))
                        if not session.blocked:
                            session.blocked, session.stop_reason = True, "sdk_getter_error"
                    else:
                        if session.blocked:
                            attempt.update(status="rejected", safe_error_class=session.stop_reason)
                        else:
                            attempt.update(status="captured", safe_error_class=None)
                    attempt["finished_at"] = now()
                    if attempt["status"] == "captured":
                        results.append({**attempt, "frame": frame.copy(deep=True)})
                    if session.blocked:
                        break
                if session.blocked:
                    break
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - retain partial captures if transport shutdown fails.
                if not session.blocked:
                    session.blocked, session.stop_reason = True, "session_shutdown_error"
    return {"results": results, "logical_attempts": attempts, "http_captures": session.http_captures,
            "financial_diagnostic_captures": session.financial_diagnostic_captures,
            "request_observations": session.request_observations, "session_request_count": session.session_request_count,
            "stopped": session.blocked, "stop_reason": session.stop_reason,
            "request_count_scope": "Session.request_dispatches; redirects_disabled; automatic_retries_disabled",
            "cache_scope": "temporary_process_private; removed_on_shutdown"}
