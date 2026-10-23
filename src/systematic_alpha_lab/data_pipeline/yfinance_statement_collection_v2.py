"""Explicit BXP/current-DOC annual and quarterly statement availability capture.

This version reuses the frozen transport rather than modifying its published
source fingerprint. It does not replace AV, certify an issuer, fill fields or
claim historical coverage parity with another provider.
"""
from __future__ import annotations

import hashlib
import importlib
import re
from pathlib import Path

import pandas as pd

from . import yfinance_collection as transport_v1

VERSION = "yf_statement_collection_v2"
TRANSPORT_SOURCE_SHA256 = "3dc3f2a9f182e48d7c3224061cdf190f4680593ed77e3c62ce0b95bbd2b62227"
SDK_FUNDAMENTALS_SOURCE_SHA256 = "26198c3ef0d577255f63b6f84106150ca2f3bb5bc86eb56e60c4cdcb73948f86"
SYMBOLS = frozenset({"BXP", "DOC"})
FREQUENCIES = ("yearly", "quarterly")
_PREFIX = {"yearly": "annual", "quarterly": "quarterly"}


def _sources():
    actual = hashlib.sha256(Path(transport_v1.__file__).read_bytes()).hexdigest()
    if actual != TRANSPORT_SOURCE_SHA256:
        raise ValueError("Frozen transport source changed; review a new collector version")
    return {"collector_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "transport_source_sha256": actual, "yfinance_version": transport_v1.YFINANCE_VERSION}


def _plan(symbols):
    symbols = transport_v1._symbols(symbols)
    if len(symbols) != 2 or frozenset(symbols) != SYMBOLS:
        raise ValueError("This version requires the explicit BXP/current-DOC availability scope")
    return [{"job_id": f"{symbol}:{statement}:{frequency}", "symbol": symbol, "method": method,
             "statement": statement, "frequency": frequency, "status": "not_attempted",
             "started_at": None, "finished_at": None, "safe_error_class": None}
            for frequency in FREQUENCIES for symbol in symbols
            for method, statement, _ in transport_v1.METHODS]


def _begin_frequency(session, job, metrics):
    """Adapt only the guarded v1 job tuple; its request/response guard is unchanged.

    This private tuple coupling is intentional and pinned to the complete v1
    source above. No metric or response bytes are rewritten to resemble annual
    data. The inherited route guard matches actual requested/meta type labels.
    """
    if job["frequency"] not in _PREFIX or not isinstance(metrics, (list, tuple)) or not metrics or any(
        not isinstance(metric, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", metric) for metric in metrics
    ) or len(set(metrics)) != len(metrics):
        session.block("frequency_plan_rejected")
    session.begin_logical(job["symbol"], job["statement"], metrics)
    expected = (job["symbol"], job["statement"], frozenset("annual" + metric for metric in metrics))
    if session._job != expected:
        session.block("transport_job_contract_changed")
    session._job = (job["symbol"], job["statement"],
                    frozenset(_PREFIX[job["frequency"]] + metric for metric in metrics))


def _tag(items, first, job):
    identity = {name: job[name] for name in ("job_id", "symbol", "statement", "frequency")}
    return [{**item, **identity} for item in items[first:]]


def collect_statement_availability(symbols, *, max_session_requests=32, min_interval_seconds=2,
                                   session_factory=None, sdk=None, now=transport_v1._utc_now):
    """Execute the fixed 12-job plan once, with one shared dispatch ceiling.

    All successful and diagnostic bodies remain exact same-call response bytes.
    Each frame requires a same-call financial capture. ``planned_jobs`` always
    contains twelve entries; ``logical_attempts`` contains only started jobs.
    A fresh process and temporary SDK caches are mandatory in the real runtime.
    Test dependencies may be injected without installing or importing yfinance.
    """
    jobs = _plan(symbols)
    if isinstance(max_session_requests, bool) or not isinstance(max_session_requests, int) or not (
        1 <= max_session_requests <= 32
    ):
        raise ValueError("This availability plan permits at most 32 shared session dispatches")
    transport_v1._positive_interval(min_interval_seconds)
    sources = _sources()
    real_sdk = sdk is None
    if real_sdk:
        sdk = importlib.import_module("yfinance")
    if sdk.__version__ != transport_v1.YFINANCE_VERSION:
        raise ValueError("The collector requires the pinned yfinance version")
    sources["sdk_fundamentals_source_sha256"] = None
    sources["expected_sdk_fundamentals_source_sha256"] = SDK_FUNDAMENTALS_SOURCE_SHA256
    if real_sdk:
        scraper = importlib.import_module("yfinance.scrapers.fundamentals")
        source_sha = hashlib.sha256(Path(scraper.__file__).read_bytes()).hexdigest()
        if source_sha != SDK_FUNDAMENTALS_SOURCE_SHA256:
            raise ValueError("Pinned SDK financial scraper source changed")
        sources["sdk_fundamentals_source_sha256"] = source_sha
    factory = session_factory or transport_v1.make_bounded_yfinance_session
    results, attempts, captures, diagnostics, observations = [], [], [], [], []
    tickers = {}
    keys = {statement: key for _, statement, key in transport_v1.METHODS}
    with transport_v1._quiet_sdk(sdk), transport_v1._private_cache(sdk, real_sdk=real_sdk):
        session = factory(tuple(symbols), max_session_requests=max_session_requests,
                          min_interval_seconds=min_interval_seconds)
        try:
            if session.blocked or session.session_request_count or session.request_observations or (
                session.http_captures or session.financial_diagnostic_captures
            ):
                raise ValueError("The collector requires a fresh bounded session")
            for job in jobs:
                first_raw, first_diagnostic, first_observation = (
                    len(session.http_captures), len(session.financial_diagnostic_captures),
                    len(session.request_observations),
                )
                job.update(started_at=now(), yfinance_version=sdk.__version__)
                try:
                    if job["symbol"] not in tickers:
                        # Constructors are outside the allowed financial job.
                        # Any unexpected network access is rejected by v1.
                        session._job = None
                        tickers[job["symbol"]] = sdk.Ticker(job["symbol"], session=session)
                    _begin_frequency(session, job, sdk.const.fundamentals_keys[keys[job["statement"]]])
                    frame = getattr(tickers[job["symbol"]], job["method"])(
                        as_dict=False, pretty=False, freq=job["frequency"],
                    )
                    if not isinstance(frame, pd.DataFrame):
                        session.block("sdk_dataframe_required")
                    if len(session.http_captures) == first_raw:
                        session.block("missing_same_call_financial_capture")
                    frame = frame.copy(deep=True)
                except Exception:  # noqa: BLE001 - never preserve provider exception text or URLs.
                    if not session.blocked:
                        session.blocked, session.stop_reason = True, "sdk_getter_error"
                    job.update(status="rejected", safe_error_class=session.stop_reason)
                else:
                    job.update(status="rejected" if session.blocked else "captured",
                               safe_error_class=session.stop_reason if session.blocked else None)
                job["finished_at"] = now()
                attempts.append(dict(job))
                captures.extend(_tag(session.http_captures, first_raw, job))
                diagnostics.extend(_tag(session.financial_diagnostic_captures, first_diagnostic, job))
                observations.extend(_tag(session.request_observations, first_observation, job))
                if job["status"] == "captured":
                    results.append({**job, "frame": frame})
                session._job = None
                if session.blocked:
                    break
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - retain completed evidence if transport shutdown fails.
                if not session.blocked:
                    session.blocked, session.stop_reason = True, "session_shutdown_error"
    return {"collector_version": VERSION, **sources, "planned_jobs": jobs, "results": results,
            "logical_attempts": attempts, "http_captures": captures, "financial_diagnostic_captures": diagnostics,
            "request_observations": observations, "session_request_count": session.session_request_count,
            "stopped": session.blocked, "stop_reason": session.stop_reason,
            "max_session_requests": max_session_requests, "min_interval_seconds": min_interval_seconds,
            "maximum_automatic_retries": 0, "redirects_enabled": False,
            "request_count_scope": "Session.request_dispatches; redirects_disabled; automatic_retries_disabled",
            "cache_scope": "temporary_process_private; removed_on_shutdown",
            "candidate_only": True, "statement_completeness": "not_certified",
            "issuer_identity_status": "unverified", "av_inputs_overwritten": False}
