"""Small, explicit Yahoo candidate captures; never a source-selection or score step."""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .offline_reader import OfflineDataReader
from .snapshot_store import SnapshotStore

NORMALIZER = "yf_pilot_capture_v1"


def _body(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def _sha(body):
    return hashlib.sha256(body).hexdigest()


def validate_pilot_plan(plan):
    """Validate the execution bound, not the truth of the research assertions.

    The research contract is retained verbatim inside this explicit plan. A
    syntactically valid company/date declaration is not an issuer or accounting
    acceptance decision. Returned vendor histories can exceed these targets.
    """
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise ValueError("Expected a versioned supplemental pilot plan")
    targets = plan.get("targets")
    if not isinstance(targets, list) or not 1 <= len(targets) <= 3:
        raise ValueError("The pilot allows one to three explicit companies")
    if not isinstance(plan.get("research_contract"), dict) or not plan["research_contract"]:
        raise ValueError("A nonempty research contract must be retained")
    symbols, ciks = [], []
    for target in targets:
        if not isinstance(target, dict):
            raise TypeError("Invalid company target")
        symbol, cik = target.get("symbol"), target.get("cik")
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,24}", symbol):
            raise ValueError("Invalid explicit provider symbol")
        if not isinstance(cik, str) or not re.fullmatch(r"[0-9]{10}", cik) or int(cik) == 0:
            raise ValueError("Declare a ten-digit company CIK; no ticker inference")
        if not isinstance(target.get("company_ref"), str) or not target["company_ref"].strip():
            raise ValueError("Declare the research company reference")
        periods = target.get("periods")
        if not isinstance(periods, list) or len(periods) != 2:
            raise ValueError("Each company needs two adjacent annual target periods")
        dates = []
        for period in periods:
            if not isinstance(period, dict) or isinstance(period.get("fiscal_year"), bool) or not isinstance(
                period.get("fiscal_year"), int
            ):
                raise TypeError("Declare each fiscal-year label")
            pair = []
            for name in ("start", "end"):
                value = period.get(name)
                if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                    raise ValueError("Declare actual ISO fiscal start and end dates")
                pair.append(date.fromisoformat(value))
            if not 300 <= (pair[1] - pair[0]).days <= 380:
                raise ValueError("Only explicitly declared annual durations are supported")
            dates.append(pair)
        if periods[1]["fiscal_year"] != periods[0]["fiscal_year"] + 1 or dates[1][0] != (
            dates[0][1] + timedelta(days=1)
        ):
            raise ValueError("Target fiscal periods must be adjacent, in source order")
        symbols.append(symbol)
        ciks.append(cik)
    if len(set(symbols)) != len(symbols) or len(set(ciks)) != len(ciks):
        raise ValueError("Duplicate target symbol or company")
    declared = plan["research_contract"].get("scope", {}).get("issuers")
    if not isinstance(declared, list) or not declared:
        raise ValueError("Research must explicitly authorize the issuer/period selection")
    authorized = {(row["yahoo_symbol"], row["cik"]): [
        {"fiscal_year": period["fiscal_year"], "start": period["period_start"], "end": period["period_end"]}
        for period in row["periods"]
    ] for row in declared}
    if any(authorized.get((target["symbol"], target["cik"])) != target["periods"] for target in targets):
        raise ValueError("Execution targets differ from the frozen research authorization")
    _body(plan)
    return symbols


def collect_yfinance_pilot(data_root, *, plan, code_commit, max_session_requests=40, collector=None):
    """Create a new root once, preserving partial results without hidden retries.

    The collector is an explicit online dependency. Offline verification below
    does not import it or yfinance. All outputs remain unaccepted candidates.
    """
    symbols = validate_pilot_plan(plan)
    if not isinstance(code_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise ValueError("Declare the exact implementation commit for this capture")
    if isinstance(max_session_requests, bool) or not isinstance(max_session_requests, int) or not (
        0 < max_session_requests <= 40
    ):
        raise ValueError("Declare a positive session-dispatch budget of at most 40")
    root = Path(data_root)
    if root.exists():
        raise ValueError("Use a new private root; existing captures are never resumed or overwritten")
    if collector is None:
        from .yfinance_collection import collect_yearly_statements
        collector = collect_yearly_statements
    collector_file = inspect.getsourcefile(collector)
    if collector_file is None:
        raise ValueError("An inspectable collector implementation is required")
    collector_sha = _sha(Path(collector_file).read_bytes())
    from .yahoo_timeseries import capture_yahoo_timeseries
    from .yfinance_snapshots import capture_yfinance_statement, encode_dataframe

    root.mkdir(parents=True, mode=0o700)
    store = SnapshotStore(root)
    plan_body = _body(plan)
    contract_sha = _sha(plan_body)
    contract_record = store.capture("supplement_research_contract", {"contract_sha256": contract_sha}, plan_body)
    response = collector(symbols, max_session_requests=max_session_requests)
    methods = {"get_income_stmt": "income", "get_balance_sheet": "balance-sheet", "get_cash_flow": "cash-flow"}
    if (isinstance(response["session_request_count"], bool) or not isinstance(response["session_request_count"], int) or
            not 0 <= response["session_request_count"] <= max_session_requests):
        raise ValueError("Collector exceeded its declared session-dispatch budget")
    identities = [(item["symbol"], item["method"]) for item in response["results"]]
    if len(set(identities)) != len(identities) or any(
        symbol not in symbols or method not in methods for symbol, method in identities
    ) or any(item["statement"] != methods[item["method"]] for item in response["results"]):
        raise ValueError("Collector results are outside the explicit logical plan")
    if any(item["symbol"] not in symbols or item["statement"] not in methods.values()
           for item in response["http_captures"]):
        raise ValueError("Financial HTTP capture is outside the explicit company plan")
    logical = {(symbol, method): {"symbol": symbol, "method": method, "statement": statement,
                                  "status": "not_attempted"}
               for symbol in symbols for method, statement in methods.items()}
    attempts = response.get("logical_attempts", [])
    if not attempts:
        attempts = [{name: item[name] for name in ("symbol", "method", "statement", "started_at", "finished_at")}
                    | {"status": "returned_dataframe"} for item in response["results"]]
    seen = set()
    for attempt in attempts:
        identity = (attempt["symbol"], attempt["method"])
        if identity not in logical or identity in seen or attempt["statement"] != logical[identity]["statement"]:
            raise ValueError("Logical attempts differ from the explicit plan")
        seen.add(identity)
        logical[identity] = attempt
    transport = {name: response[name] for name in (
        "request_observations", "stopped", "stop_reason", "session_request_count"
    )}
    transport["logical_attempts"] = list(logical.values())
    transport["code_commit"] = code_commit
    transport["collector_source_sha256"] = collector_sha
    transport["financial_responses"] = []
    transport["library_returns"] = []
    for status, items in (("validated_financial_json", response["http_captures"]),
                          ("rejected_financial_json", response.get("financial_diagnostic_captures", []))):
        for item in items:
            digest = _sha(item["body"])
            relative = f"transport_financial_json/{digest}.json"
            store._write(relative, item["body"])
            transport["financial_responses"].append({"symbol": item["symbol"], "statement": item["statement"],
                                                     "path": relative, "sha256": digest, "status": status})
    for item in response["results"]:
        entry = {name: item[name] for name in ("symbol", "method", "statement", "started_at", "finished_at")}
        try:
            body = _body({**entry, "frame": encode_dataframe(item["frame"])})
            digest = _sha(body)
            relative = f"library_return_evidence/{digest}.json"
            store._write(relative, body)
            entry.update(path=relative, sha256=digest, retention_status="typed_library_return_captured")
        except (ValueError, TypeError, OverflowError):
            entry.update(retention_status="unsupported_codec_not_captured")
        transport["library_returns"].append(entry)
    transport_body = _body(transport)
    store._write("transport-receipt.json", transport_body)
    captures, rejected, rejected_frames, http_records = [], [], [], {}
    for item in response.get("financial_diagnostic_captures", []):
        digest = _sha(item["body"])
        relative = f"rejected_financial_json/{digest}.json"
        store._write(relative, item["body"])
        rejected.append({"symbol": item["symbol"], "statement": item["statement"], "sha256": digest,
                         "path": relative, "status": "transport_schema_rejected"})
    for item in response["http_captures"]:
        identity = (item["symbol"], item["statement"])
        try:
            capture = capture_yahoo_timeseries(
                store, symbol=item["symbol"], statement=item["statement"], body=item["body"],
                observed_at=item["observed_at"], contract_sha256=contract_sha,
            )
        except (ValueError, TypeError, KeyError):
            # Only successful financial JSONs reach this list; auth/cookie bodies
            # are excluded by the transport. Retain rejected financial bytes too.
            digest = _sha(item["body"])
            relative = f"rejected_financial_json/{digest}.json"
            store._write(relative, item["body"])
            rejected.append({"symbol": identity[0], "statement": identity[1], "sha256": digest,
                             "path": relative, "status": "normalizer_rejected"})
            continue
        captures.append(capture)
        http_records.setdefault(identity, []).append(capture["record"])
    for item in response["results"]:
        try:
            capture = capture_yfinance_statement(
                store, item["frame"], symbol=item["symbol"], method=item["method"],
                yfinance_version=item["yfinance_version"], started_at=item["started_at"],
                finished_at=item["finished_at"], http_records=http_records.get((item["symbol"], item["statement"]), ()),
                contract_sha256=contract_sha,
            )
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            rejected_frames.append({"symbol": item["symbol"], "method": item["method"],
                                    "statement": item["statement"], "status": "normalizer_rejected",
                                    "safe_error_class": type(exc).__name__})
            continue
        captures.append(capture)
    manifests = [capture["manifest"] for capture in captures]
    summary = {name: response[name] for name in (
        "request_observations", "stopped", "stop_reason", "session_request_count"
    )}
    summary["logical_attempts"] = transport["logical_attempts"]
    summary["code_commit"] = code_commit
    summary["collector_source_sha256"] = collector_sha
    summary.update({"logical_results": len(response["results"]), "financial_http_responses": len(
        response["http_captures"]), "normalizer_rejections": len(rejected) + len(rejected_frames),
        "accepted_research_fields": 0})
    ledger = {"collection": summary, "rejected_financial_responses": rejected,
              "rejected_library_returns": rejected_frames}
    provenance = {
        "normalizer_source_sha256": _sha(Path(__file__).read_bytes()),
        "contract_sha256": contract_sha, "candidate_only": True,
        "target_periods_are_not_vendor_date_remappings": True,
        "transport_receipt_sha256": _sha(transport_body), "collection_ledger_sha256": _sha(_body(ledger)),
    }
    if manifests:
        provenance["input_manifests"] = manifests
    anchor_manifest = store.publish_tables(contract_record, NORMALIZER, {
        "audit": pd.DataFrame([{"candidate_only": True, "accepted_research_fields": 0,
                                "logical_results": summary["logical_results"],
                                "stopped": summary["stopped"]}]),
    }, provenance=provenance)
    receipt = {"schema_version": 1, "contract_sha256": contract_sha, "plan": plan,
               "contract_record": contract_record, "anchor_manifest": anchor_manifest,
               "captures": captures, **ledger,
               "source_policy": "AV_primary_supplement_candidates_unaccepted",
               "capture_scope": "full_yearly_getter_returns; analysis_selection_is_two_declared_periods"}
    (root / "pilot-receipt.json").write_bytes(_body(receipt) + b"\n")
    verify_yfinance_pilot(root)
    return receipt


def verify_yfinance_pilot(data_root):
    """Read every fixed receipt table and dependency; never construct a writer."""
    root = Path(data_root).resolve(strict=True)
    receipt = json.loads((root / "pilot-receipt.json").read_bytes())
    if receipt.get("schema_version") != 1:
        raise ValueError("Unknown pilot receipt version")
    validate_pilot_plan(receipt["plan"])
    if _sha(_body(receipt["plan"])) != receipt["contract_sha256"]:
        raise ValueError("Pilot contract differs from the capture receipt")
    contract = receipt["contract_record"]
    if (contract["provider"] != "supplement_research_contract" or contract["raw_sha256"] != (
        receipt["contract_sha256"]
    ) or json.loads(contract["request_json"]) != {"contract_sha256": receipt["contract_sha256"]}):
        raise ValueError("Pilot contract identity mismatch")
    reader = OfflineDataReader(root)
    anchor = receipt["anchor_manifest"]
    expected_inputs = [capture["manifest"] for capture in receipt["captures"]]
    if anchor["provenance"].get("input_manifests", []) != expected_inputs or set(anchor["tables"]) != {"audit"}:
        raise ValueError("Pilot receipt omits or changes a captured dataset")
    if anchor["snapshot_id"] != contract["id"] or anchor["raw_sha256"] != receipt["contract_sha256"]:
        raise ValueError("Pilot anchor differs from its contract capture")
    if anchor["provenance"].get("normalizer_source_sha256") != _sha(Path(__file__).read_bytes()):
        raise ValueError("Pilot implementation drift; select the original code version")
    ledger = {name: receipt[name] for name in (
        "collection", "rejected_financial_responses", "rejected_library_returns"
    )}
    transport_body = (root / "transport-receipt.json").read_bytes()
    if (anchor["provenance"].get("collection_ledger_sha256") != _sha(_body(ledger)) or
            anchor["provenance"].get("transport_receipt_sha256") != _sha(transport_body)):
        raise ValueError("Collection or failure evidence differs from its complete anchored ledger")
    transport = json.loads(transport_body)
    for name in ("request_observations", "stopped", "stop_reason", "session_request_count", "logical_attempts",
                 "code_commit", "collector_source_sha256"):
        if receipt["collection"][name] != transport[name]:
            raise ValueError("Final collection receipt differs from the original transport evidence")
    for item in [*transport["financial_responses"], *transport["library_returns"]]:
        if "path" not in item:
            continue
        path = (root / item["path"]).resolve(strict=True)
        if not path.is_relative_to(root) or _sha(path.read_bytes()) != item["sha256"]:
            raise ValueError("Transport or returned-frame evidence integrity failure")
    manifests = [anchor, *expected_inputs]
    table_count, row_count = 0, 0
    for manifest in manifests:
        if not manifest.get("tables"):
            raise ValueError("Empty receipt table set")
        expected_digest = _sha(_body(manifest))
        for table, descriptor in manifest["tables"].items():
            result = reader.read(snapshot_id=manifest["snapshot_id"], normalizer=manifest["normalizer"], table=table)
            if (result.metadata["manifest_sha256"] != expected_digest or
                    result.metadata["table_sha256"] != descriptor["sha256"] or
                    result.metadata["source_rows"] != descriptor["rows"]):
                raise ValueError("Pilot receipt differs from complete catalog evidence")
            if manifest is anchor:
                expected_record = contract
            else:
                expected_record = next(capture["record"] for capture in receipt["captures"]
                                       if capture["manifest"] is manifest)
            if any(result.metadata[name] != expected_record[name] for name in (
                "provider", "raw_sha256", "observed_at"
            )) or result.metadata["request"] != json.loads(expected_record["request_json"]):
                raise ValueError("Pilot receipt record differs from the catalog source")
            table_count += 1
            row_count += len(result.frame)
    # Verify rejected financial bodies as well, without interpreting them as
    # materialized successful datasets or accepted research inputs.
    for item in receipt["rejected_financial_responses"]:
        path = (root / item["path"]).resolve(strict=True)
        if not path.is_relative_to(root) or _sha(path.read_bytes()) != item["sha256"]:
            raise ValueError("Rejected financial response integrity failure")
    return {"tables": table_count, "rows": row_count, "candidate_only": True,
            "accepted_research_fields": 0, "collection_stopped": receipt["collection"]["stopped"]}
