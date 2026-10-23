"""Original report bytes stay exact and unreviewed; contact absence is explicit."""
import base64
import hashlib
import json
import socket
from copy import deepcopy
from types import SimpleNamespace

import pytest
import requests

from systematic_alpha_lab.data_pipeline.offline_reader import OfflineDataReader
from systematic_alpha_lab.data_pipeline.original_documents import (
    NORMALIZER,
    capture_original_document,
    collect_original_documents,
    document_request,
    replay_original_document,
)
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore

NOW = "2026-01-15T12:00:00+00:00"
BODY = b'<!DOCTYPE html><html><body>synthetic 9007199254740993 \xe2\x88\x92 1.2300</body></html>'


def request(sec=False):
    return document_request(url="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/annual.htm" if sec
                            else "https://issuer.example/annual.htm", cik="0000000001",
                            accession="0000000001-26-000001", document_role="synthetic annual report")


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = next(self.responses)
        if isinstance(item, BaseException):
            raise item
        return item


def response(status=200, body=BODY, media="text/html; charset=utf-8"):
    return SimpleNamespace(status_code=status, content=body, headers={"Content-Type": media},
                           iter_content=lambda **kw: iter([body]), close=lambda: None)


def test_exact_document_bytes_replay_with_read_only_reader(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    captured = capture_original_document(store, request=request(), body=BODY, media_type="text/html", observed_at=NOW)
    assert replay_original_document(store, captured["record"]) == captured["manifest"]
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline document reading attempted collection")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(SnapshotStore, "__init__", forbidden)
    value = OfflineDataReader(tmp_path).read(snapshot_id=captured["record"]["id"], normalizer=NORMALIZER, table="document")
    row = value.frame.iloc[0]
    assert base64.b64decode(row.document_base64, validate=True) == BODY
    assert row.document_sha256 == hashlib.sha256(BODY).hexdigest()
    assert row.research_acceptance == "unreviewed"


def test_missing_sec_contact_is_zero_sec_requests_but_issuer_still_proceeds(tmp_path):
    transport = Transport([response()])
    result = collect_original_documents(SnapshotStore(tmp_path), plan=[request(True), request()],
                                        max_requests=1, session=transport, min_interval_seconds=.2)
    assert result["session_request_count"] == 1
    assert len(transport.calls) == 1 and transport.calls[0][0].startswith("https://issuer.example/")
    assert not transport.calls[0][1]["allow_redirects"]
    assert result["outcomes"][0]["status"] == "missing_authorized_sec_contact"
    assert len(result["captures"]) == 1


@pytest.mark.parametrize("first", [response(429), response(302), requests.ConnectionError("sensitive diagnostic")])
def test_first_failure_stops_without_redirect_or_retry(tmp_path, first):
    second = deepcopy(request())
    second["url"] = "https://issuer.example/second.htm"
    transport = Transport([first, response()])
    result = collect_original_documents(SnapshotStore(tmp_path), plan=[request(), second], max_requests=2,
                                        session=transport, min_interval_seconds=.2)
    assert len(transport.calls) == result["session_request_count"] == 1
    assert result["unattempted_requests"] == 1 and not result["captures"]
    assert "sensitive diagnostic" not in json.dumps(result)


def test_budget_and_invalid_contact_preflight_make_no_calls(tmp_path):
    transport = Transport([])
    store = SnapshotStore(tmp_path)
    with pytest.raises(ValueError):
        collect_original_documents(store, plan=[request()], max_requests=0, session=transport)
    with pytest.raises(ValueError):
        collect_original_documents(store, plan=[request(True)], max_requests=1, sec_user_agent="invented", session=transport)
    assert not transport.calls


@pytest.mark.parametrize("changes", [
    {"url": "http://issuer.example/a.htm"},
    {"url": "https://issuer.example/a.htm?credential=private"},
    {"url": "https://user:pass@issuer.example/a.htm"},
    {"cik": "1"},
    {"accession": "../../other"},
    {"url": "https://www.sec.gov/Archives/edgar/data/2/000000000126000001/a.htm"},
    {"url": "https://data.sec.gov/Archives/edgar/data/1/000000000126000001/a.htm"},
    {"url": "https://www.sec.gov./Archives/edgar/data/1/000000000126000001/a.htm"},
    {"url": "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/.."},
])
def test_unbounded_or_inconsistent_document_requests_rejected(changes):
    value = request()
    value.update(changes)
    with pytest.raises(ValueError):
        document_request(**value)


def test_stream_size_limit_stops_and_closes_without_capturing(tmp_path):
    first = response()
    closed = []
    first.iter_content = lambda **kw: iter([b"x" * 65536] * 481)
    first.close = lambda: closed.append(True)
    transport = Transport([first])
    result = collect_original_documents(SnapshotStore(tmp_path), plan=[request()], max_requests=1, session=transport)
    assert not result["captures"] and result["outcomes"][0]["status"] == "document_size_limit"
    assert closed == [True]


def test_pdf_bytes_and_source_code_drift_are_checked(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    with pytest.raises(ValueError):
        capture_original_document(store, request=request(), body=BODY, media_type="application/pdf", observed_at=NOW)
    captured = capture_original_document(store, request=request(), body=b"%PDF-1.7\nsynthetic", media_type="application/pdf",
                                         observed_at=NOW)
    manifest = deepcopy(captured["manifest"])
    manifest["provenance"]["normalizer_source_sha256"] = "0" * 64
    with store._db() as db:
        db.execute("UPDATE datasets SET manifest_json=? WHERE snapshot_id=?", (json.dumps(manifest), captured["record"]["id"]))
    with pytest.raises(ValueError):
        replay_original_document(store, captured["record"])
