"""Explicit original-report bytes in the shared store, without fact interpretation."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import requests

from .sec_snapshots import SECClient
from .snapshot_store import SnapshotStore, utc_time

PROVIDER = "original_financial_document"
NORMALIZER = "original_document_bytes_v1"


def document_request(*, url, cik, accession, document_role):
    if not isinstance(url, str):
        raise TypeError("Declare a public original-report URL")
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password or
            parts.query or parts.fragment or parts.port is not None or parts.hostname.endswith(".")):
        raise ValueError("Only an explicit HTTPS report URL without credentials or query is supported")
    if not isinstance(cik, str) or not re.fullmatch(r"[0-9]{10}", cik) or int(cik) == 0:
        raise ValueError("Declare the company CIK without ticker inference")
    if not isinstance(accession, str) or not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
        raise ValueError("Declare the research-selected filing accession")
    if not isinstance(document_role, str) or not document_role.strip():
        raise ValueError("Declare the document's proposed evidence role")
    if parts.hostname in {"sec.gov", "www.sec.gov"}:
        prefix = f"/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
        if (not parts.path.startswith(prefix) or parts.path[len(prefix):] in {".", ".."} or
                not re.fullmatch(r"[A-Za-z0-9_.-]+", parts.path[len(prefix):])):
            raise ValueError("SEC report URL differs from the explicit issuer/accession")
    elif parts.hostname.endswith(".sec.gov"):
        raise ValueError("Only the explicit SEC Archives document endpoint is supported")
    return {"url": url, "cik": cik, "accession": accession, "document_role": document_role}


def _canonical(request):
    if not isinstance(request, dict) or set(request) != {"url", "cik", "accession", "document_role"}:
        raise ValueError("Expected an explicit original-document request")
    return document_request(**request)


def capture_original_document(store, *, request, body, media_type, observed_at):
    """Wrap exact document bytes explicitly; the JSON envelope is not HTTP raw."""
    request = _canonical(request)
    if not isinstance(body, bytes) or not 1 <= len(body) <= 30 * 1024 * 1024:
        raise ValueError("Expected a nonempty report no larger than 30 MiB")
    media = media_type.lower().split(";", 1)[0].strip() if isinstance(media_type, str) else None
    if media not in {"text/html", "application/xhtml+xml", "application/pdf"}:
        raise ValueError("Unsupported original-report content type")
    if media == "application/pdf" and not body.startswith(b"%PDF-"):
        raise ValueError("Source bytes differ from the declared PDF media type")
    if media != "application/pdf" and b"<html" not in body[:65536].lower():
        raise ValueError("Source bytes differ from the declared HTML media type")
    payload = {"schema": "original_document_capture_v1", "capture_layer": "encoded_original_document_bytes",
               "request": request, "media_type": media, "document_sha256": hashlib.sha256(body).hexdigest(),
               "document_length": len(body), "document_base64": base64.b64encode(body).decode("ascii")}
    record = store.capture(PROVIDER, request, json.dumps(payload, sort_keys=True).encode(), observed_at=observed_at)
    return {"record": record, "manifest": replay_original_document(store, record)}


def replay_original_document(store, record):
    registered = store.get(record["id"])
    if registered != record or record["provider"] != PROVIDER:
        raise ValueError("Original-document record differs from its exact catalog pin")
    request = _canonical(json.loads(record["request_json"]))
    if record["request_id"] != SnapshotStore.request_id(PROVIDER, request):
        raise ValueError("Original-document request differs from its catalog identity")
    path = Path(record["raw_path"])
    if path.is_absolute() or ".." in path.parts or "\\" in record["raw_path"] or not (
        store.root / path
    ).resolve(strict=True).is_relative_to(store.root):
        raise ValueError("Original-document envelope escapes its data root")
    payload = store.read_payload(record)
    if payload.get("schema") != "original_document_capture_v1" or payload.get("request") != request or (
        payload.get("capture_layer") != "encoded_original_document_bytes"
    ):
        raise ValueError("Original-document envelope differs from its source identity")
    try:
        body = base64.b64decode(payload["document_base64"], validate=True)
    except (KeyError, ValueError, TypeError):
        raise ValueError("Invalid encoded original-document bytes") from None
    if len(body) != payload.get("document_length") or hashlib.sha256(body).hexdigest() != payload.get("document_sha256"):
        raise ValueError("Original-document content integrity failure")
    provenance = {"normalizer_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "source_request": request, "source_provider": PROVIDER,
                  "source_observed_at": record["observed_at"], "accounting_facts_interpreted": False}
    existing = store.dataset(record["id"], NORMALIZER)
    if existing is not None:
        if existing["provenance"] != provenance or set(existing["tables"]) != {"document"}:
            raise ValueError("Document normalizer drift; select the original code version")
        return existing
    frame = pd.DataFrame([{**request, "snapshot_id": record["id"], "provider": PROVIDER, "normalizer": NORMALIZER,
                           "media_type": payload["media_type"], "document_sha256": payload["document_sha256"],
                           "document_length": len(body), "document_base64": payload["document_base64"],
                           "observed_at": pd.Timestamp(record["observed_at"]), "research_acceptance": "unreviewed"}])
    return store.publish_tables(record, NORMALIZER, {"document": frame}, provenance=provenance)


def collect_original_documents(store, *, plan, max_requests, sec_user_agent=None, session=None,
                               min_interval_seconds=2):
    """Fetch only the declared URLs once; no redirects, retries or discovery.

    SEC identification must be supplied from an existing authorized setting.
    Missing SEC identification is reported per document before any SEC request;
    explicitly planned issuer-hosted documents can still proceed.
    """
    if not isinstance(plan, list) or not plan or len(plan) > 8:
        raise ValueError("Declare at most eight original-document requests")
    if isinstance(max_requests, bool) or not isinstance(max_requests, int) or not 0 <= max_requests <= 8:
        raise ValueError("The original-document request ceiling is eight")
    if isinstance(min_interval_seconds, bool) or not isinstance(min_interval_seconds, (int, float)) or not (
        0.2 <= min_interval_seconds <= 60
    ):
        raise ValueError("Invalid original-document spacing")
    requests_ = [_canonical(item) for item in plan]
    if len({json.dumps(item, sort_keys=True) for item in requests_}) != len(requests_):
        raise ValueError("Duplicate original-document requests")
    sec = SECClient(sec_user_agent, min_interval_seconds=min_interval_seconds) if sec_user_agent is not None else None
    if sec is not None:
        sec.session.close()
    eligible = [item for item in requests_ if urlsplit(item["url"]).hostname not in {"sec.gov", "www.sec.gov"} or sec]
    if len(eligible) > max_requests:
        raise ValueError("Original-document budget preflight failed; no calls made")
    transport = session if session is not None else requests.Session()
    captures, outcomes, count, last_completed = [], [], 0, None
    for request in requests_:
        is_sec = urlsplit(request["url"]).hostname in {"sec.gov", "www.sec.gov"}
        if is_sec and sec is None:
            outcomes.append({"request": request, "status": "missing_authorized_sec_contact", "dispatched": False,
                             "observed_at": utc_time().isoformat(), "http_status": None})
            continue
        if last_completed is not None:
            time.sleep(max(0, min_interval_seconds - (time.monotonic() - last_completed)))
        count += 1
        response = None
        attempt = {"started_at": utc_time().isoformat(), "response_received_at": None, "finished_at": None,
                   "http_status": None}
        try:
            response = transport.get(request["url"], headers={"User-Agent": sec_user_agent if is_sec else
                                     "SRG original-report research pipeline", "Accept": "text/html,application/pdf"},
                                     timeout=(10, 60), allow_redirects=False, stream=True)
            attempt.update(response_received_at=utc_time().isoformat(), http_status=response.status_code)
            if response.status_code != 200:
                outcomes.append({"request": request, "status": f"http_{response.status_code}", "dispatched": True,
                                 "body_capture_status": "withheld_non200", "transport": attempt})
                break
            chunks, length = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                length += len(chunk)
                if length > 30 * 1024 * 1024:
                    break
                chunks.append(chunk)
            if length > 30 * 1024 * 1024:
                outcomes.append({"request": request, "status": "document_size_limit", "dispatched": True,
                                 "body_capture_status": "truncated_withheld", "transport": attempt})
                break
            body = b"".join(chunks)
        except requests.RequestException:
            outcomes.append({"request": request, "status": "transport_failed", "dispatched": True,
                             "transport": attempt})
            break
        finally:
            if response is not None:
                response.close()
            last_completed = time.monotonic()
            attempt["finished_at"] = utc_time().isoformat()
        if sec is not None and sec._contact_email.encode() in body:
            outcomes.append({"request": request, "status": "contact_echo_withheld", "dispatched": True,
                             "transport": attempt})
            break
        try:
            capture = capture_original_document(store, request=request, body=body,
                                                media_type=response.headers.get("Content-Type"), observed_at=utc_time())
        except (ValueError, TypeError):
            outcomes.append({"request": request, "status": "unsupported_source_document", "dispatched": True,
                             "body_sha256": hashlib.sha256(body).hexdigest(),
                             "body_capture_status": "withheld_unsupported_document", "transport": attempt})
            break
        captures.append(capture)
        outcomes.append({"request": request, "status": "captured_unreviewed", "dispatched": True,
                         "snapshot_id": capture["record"]["id"], "transport": attempt})
    if session is None:
        transport.close()
    return {"captures": captures, "outcomes": outcomes, "session_request_count": count,
            "unattempted_requests": len(requests_) - len(outcomes), "research_acceptance": "unreviewed"}
