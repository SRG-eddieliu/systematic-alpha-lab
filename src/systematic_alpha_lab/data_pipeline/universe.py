"""Freeze explicit current constituents and provider mappings without inference.

This module does not fetch a list, resolve tickers, or establish that a source is
an accurate index list. Verification is an explicit, evidence-bearing input.
The complete manifest belongs in the private data root; use the aggregate
summary for public evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

SCHEMA_VERSION = "srg_universe_v1"
SOURCE_KINDS = frozenset({"exact_index", "secondary_index", "etf_proxy"})
MAPPING_STATUSES = frozenset({"verified", "unverified", "unavailable"})
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,159}")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,24}")
_HASH = re.compile(r"[0-9a-f]{64}")


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _text(value, field, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} must be a nonempty trimmed string")
    return value


def _label(value, field):
    if not isinstance(value, str) or not _LABEL.fullmatch(value):
        raise ValueError(f"{field} must be an explicit identifier")
    return value


def _digest(value, field):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA256 digest")
    return value


def _date(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must be a valid date") from None


def _timestamp(value, field):
    if not isinstance(value, str):
        raise TypeError(f"{field} must be an aware ISO timestamp")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be an aware ISO timestamp") from None
    if stamp.tzinfo is None:
        raise ValueError(f"{field} must be an aware ISO timestamp")
    return stamp.astimezone(timezone.utc)


def _url(value, field):
    _text(value, field)
    parsed = urlsplit(value)
    secret_tokens = ("key", "token", "password", "passwd", "secret", "credential", "auth", "signature")
    names = {re.sub(r"[^a-z]", "", key.lower()) for key, _ in parse_qsl(parsed.query)}
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or any(token in name for token in secret_tokens for name in names)
            or parsed.fragment):
        raise ValueError(f"{field} must be an HTTPS evidence URL without credentials or fragments")
    return value


def _urls(value, field):
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a list of evidence URLs")
    result = [_url(item, field) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{field} contains duplicate evidence URLs")
    return sorted(result)


def _fields(value, required, optional, field):
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - optional:
        raise ValueError(f"Unexpected or missing {field} fields")


def _receipt(value):
    _fields(value, {"source_url", "captured_at", "as_of", "raw_sha256", "kind", "verification"},
            {"source_status"}, "source receipt")
    captured = _timestamp(value["captured_at"], "captured_at")
    as_of = _date(value["as_of"], "as_of")
    if as_of > captured.date():
        raise ValueError("Universe as_of cannot be later than the UTC capture date")
    if value["kind"] not in SOURCE_KINDS:
        raise ValueError("Unsupported universe source kind")
    status = value.get("source_status", "unknown")
    if status not in {"current", "stale", "unknown"}:
        raise ValueError("Unsupported source freshness status")
    verification = value["verification"]
    _fields(verification, {"status", "scope", "method", "evidence_urls"}, {"notes"}, "verification")
    if verification["status"] not in {"verified", "unverified", "failed"}:
        raise ValueError("Unsupported source verification status")
    if verification["scope"] not in {"full_constituents", "partial", "unverified"}:
        raise ValueError("Unsupported source verification scope")
    method = _text(verification["method"], "verification method", nullable=True)
    evidence = _urls(verification["evidence_urls"], "verification evidence")
    if verification["status"] == "verified" and (not evidence or method is None):
        raise ValueError("Verified membership requires a method and evidence URLs")
    result = {
        "source_url": _url(value["source_url"], "source_url"),
        "captured_at": captured.isoformat(), "as_of": as_of.isoformat(),
        "raw_sha256": _digest(value["raw_sha256"], "raw_sha256"),
        "kind": value["kind"], "source_status": status,
        "verification": {"status": verification["status"], "scope": verification["scope"],
                         "method": method, "evidence_urls": evidence,
                         "notes": _text(verification.get("notes"), "verification notes", nullable=True)},
    }
    if result["kind"] == "exact_index" and not _is_exact(result):
        raise ValueError("Exact index claims require current, verified full-constituent evidence")
    return result


def _is_exact(receipt):
    verification = receipt["verification"]
    return (receipt["kind"] == "exact_index" and receipt["source_status"] == "current"
            and verification["status"] == "verified" and verification["scope"] == "full_constituents")


def freeze_universe(records, source_receipt, *, index_name="S&P 500") -> dict:
    """Create a deterministic manifest from explicit security/company identities.

    Each record declares one provider mapping. Mapping punctuation is never
    transformed. CIK identifies a company and cannot serve as a security ID.
    A secondary list or ETF holding list keeps that kind after verification.
    """
    receipt = _receipt(source_receipt)
    if not isinstance(records, (list, tuple)) or not records:
        raise ValueError("Declare a nonempty explicit security list")
    companies, securities, security_ids, source_symbols, provider_companies = {}, [], set(), set(), {}
    required = {"security_id", "company_id", "company_name", "security_name", "source_symbol", "provider",
                "provider_symbol", "provider_symbol_status", "mapping_evidence"}
    for row in records:
        _fields(row, required, {"cik", "exchange", "share_class"}, "security record")
        security_id = _label(row["security_id"], "security_id")
        company_id = None if row["company_id"] is None else _label(row["company_id"], "company_id")
        if security_id == company_id or re.fullmatch(r"(?:cik[:._-]?)?\d{1,10}", security_id, re.IGNORECASE):
            raise ValueError("A company/CIK identity cannot be used as a security_id")
        source_symbol = _text(row["source_symbol"], "source_symbol")
        if security_id in security_ids or source_symbol in source_symbols:
            raise ValueError("Duplicate security identity or source symbol")
        security_ids.add(security_id)
        source_symbols.add(source_symbol)
        cik = row.get("cik")
        if cik is not None:
            if not isinstance(cik, str) or not re.fullmatch(r"\d{1,10}", cik) or int(cik) == 0:
                raise ValueError("CIK must be a nonzero company identifier of at most ten digits")
            cik = cik.zfill(10)
        if company_id is None:
            if row["company_name"] is not None or cik is not None:
                raise ValueError("Unmapped company identity must not assert a company name or CIK")
        else:
            company = {"company_id": company_id, "company_name": _text(row["company_name"], "company_name"), "cik": cik}
            if company_id in companies and companies[company_id] != company:
                raise ValueError("Conflicting company identity attributes")
            if cik is not None and any(other["cik"] == cik and other["company_id"] != company_id
                                       for other in companies.values()):
                raise ValueError("A company CIK cannot have conflicting company identities")
            companies[company_id] = company
        provider = _label(row["provider"], "provider")
        mapping_status = row["provider_symbol_status"]
        if mapping_status not in MAPPING_STATUSES:
            raise ValueError("Unsupported provider mapping status")
        symbol = row["provider_symbol"]
        if mapping_status == "unavailable":
            if symbol is not None:
                raise ValueError("Unavailable provider mapping must have a null symbol")
        elif not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
            raise ValueError("Declare an explicit provider symbol without punctuation inference")
        evidence = _urls(row["mapping_evidence"], "mapping_evidence")
        if mapping_status == "verified" and not evidence:
            raise ValueError("Verified provider mapping requires evidence URLs")
        if symbol is not None:
            key = (provider, symbol)
            if company_id is not None and key in provider_companies and provider_companies[key] != company_id:
                raise ValueError("One provider symbol cannot identify conflicting companies")
            if company_id is not None:
                provider_companies[key] = company_id
        securities.append({
            "security_id": security_id, "company_id": company_id,
            "security_name": _text(row["security_name"], "security_name"), "source_symbol": source_symbol,
            "exchange": _text(row.get("exchange"), "exchange", nullable=True),
            "share_class": _text(row.get("share_class"), "share_class", nullable=True),
            "provider": provider, "provider_symbol": symbol, "provider_symbol_status": mapping_status,
            "mapping_evidence": evidence,
        })
    unresolved = sum(row["company_id"] is None for row in securities)
    manifest = {
        "schema_version": SCHEMA_VERSION, "index_name": _text(index_name, "index_name"),
        "membership_basis": "current_only", "source_receipt": receipt,
        "security_count": len(securities), "company_count": None if unresolved else len(companies),
        "identified_company_count": len(companies), "unresolved_company_security_count": unresolved,
        "companies": sorted(companies.values(), key=lambda item: item["company_id"]),
        "securities": sorted(securities, key=lambda item: item["security_id"]),
    }
    manifest["manifest_sha256"] = hashlib.sha256(_canonical(manifest)).hexdigest()
    return manifest


def validate_universe(manifest) -> dict:
    """Validate content, version, ordering and digest; return an independent copy."""
    required = {"schema_version", "index_name", "membership_basis", "source_receipt", "security_count",
                "company_count", "identified_company_count", "unresolved_company_security_count",
                "companies", "securities", "manifest_sha256"}
    _fields(manifest, required, set(), "universe manifest")
    if manifest["schema_version"] != SCHEMA_VERSION or manifest["membership_basis"] != "current_only":
        raise ValueError("Unsupported universe version or membership basis")
    _digest(manifest["manifest_sha256"], "manifest_sha256")
    if not isinstance(manifest["companies"], list) or not isinstance(manifest["securities"], list):
        raise TypeError("Universe companies and securities must be arrays")
    companies = {}
    for company in manifest["companies"]:
        _fields(company, {"company_id", "company_name", "cik"}, set(), "company")
        company_id = _label(company["company_id"], "company_id")
        if company_id in companies:
            raise ValueError("Duplicate company identity")
        companies[company_id] = company
    records = []
    for security in manifest["securities"]:
        if not isinstance(security, dict) or "company_id" not in security:
            raise ValueError("Security must reference a declared company identity")
        company_id = security["company_id"]
        if company_id is None:
            company = {"company_name": None, "cik": None}
        elif company_id in companies:
            company = companies[company_id]
        else:
            raise ValueError("Security must reference a declared company identity")
        records.append({**security, **company})
    rebuilt = freeze_universe(records, manifest["source_receipt"], index_name=manifest["index_name"])
    if _canonical(rebuilt) != _canonical(manifest):
        raise ValueError("Universe manifest content, counts, ordering or hash mismatch")
    return rebuilt


def require_universe_scope(manifest, *, as_of=None, historical=False, require_exact=False) -> dict:
    """Gate a declared use; this version cannot support historical membership."""
    manifest = validate_universe(manifest)
    if not isinstance(historical, bool) or not isinstance(require_exact, bool):
        raise TypeError("Universe scope flags must be booleans")
    if historical or (as_of is not None and _date(as_of, "as_of").isoformat() != manifest["source_receipt"]["as_of"]):
        raise ValueError("Current-only universe cannot establish historical constituents")
    if require_exact and not _is_exact(manifest["source_receipt"]):
        raise ValueError("Source is not a current verified exact index list")
    return manifest


def provider_requests(manifest, *, provider="alpha_vantage", require_verified=True,
                      include_unavailable=False) -> list[dict]:
    """Return unique explicit symbols with linked identities, without requests.

    Unavailable mappings block collection. With require_verified=False and
    include_unavailable=True they remain explicit null-symbol blocked rows.
    Unverified mappings require an opt-in and keep their status in the result.
    """
    manifest = validate_universe(manifest)
    _label(provider, "provider")
    if not isinstance(require_verified, bool) or not isinstance(include_unavailable, bool):
        raise TypeError("Mapping gate flags must be booleans")
    rows = [row for row in manifest["securities"] if row["provider"] == provider]
    if not rows:
        raise ValueError("Universe has no mappings for the requested provider")
    if not include_unavailable and any(row["provider_symbol_status"] == "unavailable" for row in rows):
        raise ValueError("Universe contains unavailable provider mappings")
    if require_verified and any(row["provider_symbol_status"] != "verified" for row in rows):
        raise ValueError("Universe contains unverified provider mappings")
    result = {}
    for row in rows:
        symbol = row["provider_symbol"]
        key = (symbol or "", row["security_id"] if symbol is None else "")
        item = result.setdefault(key, {"provider_symbol": symbol, "security_ids": [], "company_ids": [],
                                      "mapping_status": "verified"})
        item["security_ids"].append(row["security_id"])
        if row["company_id"] is not None and row["company_id"] not in item["company_ids"]:
            item["company_ids"].append(row["company_id"])
        if row["provider_symbol_status"] != "verified":
            item["mapping_status"] = row["provider_symbol_status"]
    return [dict(item, security_ids=sorted(item["security_ids"]), company_ids=sorted(item["company_ids"]))
            for _, item in sorted(result.items())]


def public_universe_summary(manifest) -> dict:
    """Allowlisted aggregate evidence: no source URLs, row IDs or local paths."""
    manifest = validate_universe(manifest)
    receipt = manifest["source_receipt"]
    return {
        "schema_version": SCHEMA_VERSION, "manifest_sha256": manifest["manifest_sha256"],
        "source_raw_sha256": receipt["raw_sha256"],
        "membership_basis": "current_only", "as_of": receipt["as_of"], "captured_at": receipt["captured_at"],
        "source_kind": receipt["kind"], "source_status": receipt["source_status"],
        "verification_status": receipt["verification"]["status"],
        "verification_scope": receipt["verification"]["scope"], "exact_index_verified": _is_exact(receipt),
        "security_count": manifest["security_count"], "company_count": manifest["company_count"],
        "identified_company_count": manifest["identified_company_count"],
        "unresolved_company_security_count": manifest["unresolved_company_security_count"],
        "mapping_status_counts": {status: sum(row["provider_symbol_status"] == status
                                              for row in manifest["securities"])
                                  for status in sorted(MAPPING_STATUSES)},
    }


def write_universe(manifest, path) -> Path:
    """Atomically create a private immutable JSON manifest; never replace it."""
    content = _canonical(validate_universe(manifest)) + b"\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != content:
                raise ValueError("Immutable universe manifest already exists with different content") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def load_universe(path) -> dict:
    """Read and validate a pinned manifest offline without creating files."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate universe JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite universe JSON constant")

    return validate_universe(json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                                        parse_constant=invalid_constant))
