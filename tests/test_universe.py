import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from systematic_alpha_lab.data_pipeline.universe import (
    freeze_universe,
    load_universe,
    provider_requests,
    public_universe_summary,
    require_universe_scope,
    validate_universe,
    write_universe,
)


def receipt(**changes):
    result = {
        "source_url": "https://example.org/current-index.csv",
        "captured_at": "2026-10-23T01:00:00Z", "as_of": "2026-10-22",
        "raw_sha256": hashlib.sha256(b"synthetic constituent source").hexdigest(),
        "kind": "secondary_index", "source_status": "unknown",
        "verification": {"status": "unverified", "scope": "unverified", "method": None, "evidence_urls": []},
    }
    result.update(changes)
    return result


def security(symbol="SYNTH.A", **changes):
    result = {
        "security_id": "synthetic-security-class-a", "company_id": "synthetic-company",
        "security_name": "Synthetic Class A", "company_name": "Synthetic Company",
        "source_symbol": symbol, "provider": "alpha_vantage", "provider_symbol": symbol,
        "provider_symbol_status": "unverified", "mapping_evidence": [], "cik": "1234567", "share_class": "A",
    }
    result.update(changes)
    return result


def exact_receipt():
    return receipt(kind="exact_index", source_status="current", verification={
        "status": "verified", "scope": "full_constituents", "method": "full membership checked against index publisher",
        "evidence_urls": ["https://example.org/publisher/full-constituents"],
    })


def verified_security(symbol="SYNTH.A", **changes):
    return security(symbol, provider_symbol_status="verified",
                    mapping_evidence=["https://example.org/provider/security-identity"], **changes)


def test_freeze_is_deterministic_counts_securities_and_companies_separately():
    first = security()
    second = security("SYNTH.B", security_id="synthetic-security-class-b", security_name="Synthetic Class B",
                      share_class="B")
    records, source = [first, second], receipt()
    before_records, before_source = deepcopy(records), deepcopy(source)
    manifest = freeze_universe(records, source)
    assert manifest == freeze_universe(list(reversed(records)), source)
    assert records == before_records and source == before_source
    assert manifest["security_count"] == 2 and manifest["company_count"] == 1
    assert manifest["companies"][0]["cik"] == "0001234567"
    assert "cik" not in manifest["securities"][0]
    assert manifest["source_receipt"]["captured_at"] == "2026-10-23T01:00:00+00:00"
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    body = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    assert manifest["manifest_sha256"] == hashlib.sha256(body).hexdigest()


def test_explicit_symbols_are_preserved_without_punctuation_conversion():
    manifest = freeze_universe([security("BRK.B", provider_symbol="BRK.B")], receipt())
    assert manifest["securities"][0]["provider_symbol"] == "BRK.B"
    with pytest.raises(ValueError, match="unverified"):
        provider_requests(manifest)
    assert provider_requests(manifest, require_verified=False)[0]["provider_symbol"] == "BRK.B"
    changed = freeze_universe([security("BRK.B", provider_symbol="BRK-B")], receipt())
    assert manifest["manifest_sha256"] != changed["manifest_sha256"]


def test_provider_plan_deduplicates_same_company_without_losing_securities():
    first = verified_security()
    second = verified_security("SYNTH.B", security_id="synthetic-security-class-b", provider_symbol="SYNTH.A")
    plan = provider_requests(freeze_universe([first, second], receipt()))
    assert plan == [{"provider_symbol": "SYNTH.A", "security_ids": ["synthetic-security-class-a",
                                                                    "synthetic-security-class-b"],
                     "company_ids": ["synthetic-company"], "mapping_status": "verified"}]


def test_unresolved_issuer_identity_stays_null_without_name_or_cik_inference():
    manifest = freeze_universe([security(company_id=None, company_name=None, cik=None)], receipt())
    assert manifest["company_count"] is None and manifest["identified_company_count"] == 0
    assert manifest["unresolved_company_security_count"] == 1 and manifest["companies"] == []
    assert validate_universe(manifest) == manifest
    assert provider_requests(manifest, require_verified=False)[0]["company_ids"] == []
    with pytest.raises(ValueError, match="Unmapped company"):
        freeze_universe([security(company_id=None)], receipt())


@pytest.mark.parametrize("options", [
    {}, {"require_verified": False}, {"require_verified": False, "include_unavailable": True},
])
def test_provider_plan_rejects_mixed_provider_scope_without_dropping_securities(options):
    records = [verified_security(), verified_security("SYNTH.B", security_id="second-security", provider="other")]
    manifest = freeze_universe(records, receipt())
    before = deepcopy(manifest)
    for provider in ("alpha_vantage", "other", "missing"):
        with pytest.raises(ValueError, match="Complete universe scope lacks mappings"):
            provider_requests(manifest, provider=provider, **options)
    assert manifest == before and manifest["security_count"] == 2
    explicit_subset = freeze_universe([records[0]], receipt())
    assert len(provider_requests(explicit_subset)) == 1


@pytest.mark.parametrize("kind", ["secondary_index", "etf_proxy"])
def test_non_exact_sources_cannot_pass_exact_claim_gate_even_if_verified(kind):
    source = exact_receipt()
    source["kind"] = kind
    manifest = freeze_universe([verified_security()], source)
    assert public_universe_summary(manifest)["exact_index_verified"] is False
    with pytest.raises(ValueError, match="exact index"):
        require_universe_scope(manifest, require_exact=True)
    assert require_universe_scope(manifest)["source_receipt"]["kind"] == kind


@pytest.mark.parametrize("change", [
    {"verification": {"status": "unverified", "scope": "unverified", "method": None, "evidence_urls": []}},
    {"source_status": "stale"}, {"source_status": "unknown"},
    {"verification": {"status": "verified", "scope": "partial", "method": "partial check",
                      "evidence_urls": ["https://example.org/evidence"]}},
])
def test_exact_claim_rejects_unverified_incomplete_or_stale_receipts(change):
    source = exact_receipt()
    source.update(change)
    with pytest.raises(ValueError, match="Exact index"):
        freeze_universe([security()], source)


def test_exact_list_requires_explicit_current_full_verification():
    manifest = freeze_universe([security()], exact_receipt())
    assert require_universe_scope(manifest, require_exact=True)["security_count"] == 1
    assert public_universe_summary(manifest)["exact_index_verified"] is True


@pytest.mark.parametrize("scope", [{"historical": True}, {"as_of": "2020-01-01"}, {"as_of": "2026-10-23"}])
def test_current_universe_is_never_historical_membership(scope):
    manifest = freeze_universe([security()], receipt())
    with pytest.raises(ValueError, match="historical constituents"):
        require_universe_scope(manifest, **scope)
    assert require_universe_scope(manifest, as_of="2026-10-22") == manifest


@pytest.mark.parametrize("change", [
    {"as_of": "2026-10-24"}, {"as_of": "2026-02-30"}, {"captured_at": "2026-10-23"},
    {"raw_sha256": "bad"}, {"source_url": "file:///private/source.csv"},
    {"source_url": "https://example.org/source?api_key=secret"},
    {"source_url": "https://example.org/source?access_token=secret"},
    {"source_url": "https://example.org/source?X-Amz-Credential=secret"},
    {"source_url": "https://user:password@example.org/source"}, {"source_status": "fresh-ish"},
])
def test_receipts_reject_future_dates_naive_times_invalid_hashes_and_credentials(change):
    with pytest.raises(ValueError):
        freeze_universe([security()], receipt(**change))


@pytest.mark.parametrize("change", [
    {"security_id": "cik:1234567"}, {"security_id": "0001234567"}, {"security_id": "synthetic-company"},
    {"provider_symbol": None}, {"provider_symbol": "SYNTH/A"}, {"provider_symbol_status": "verified"},
    {"provider_symbol_status": "unavailable"}, {"cik": "not-a-cik"},
    {"mapping_evidence": ["file:///private/mapping.json"]}, {"apikey": "forbidden-extra-field"},
])
def test_records_require_explicit_security_identity_and_evidence(change):
    with pytest.raises(ValueError):
        freeze_universe([security(**change)], receipt())


def test_unavailable_mapping_can_be_frozen_but_blocks_requests():
    manifest = freeze_universe([security(provider_symbol=None, provider_symbol_status="unavailable")], receipt())
    for verified in (True, False):
        with pytest.raises(ValueError, match="unavailable"):
            provider_requests(manifest, require_verified=verified)
    blocked = provider_requests(manifest, require_verified=False, include_unavailable=True)
    assert blocked == [{"provider_symbol": None, "security_ids": ["synthetic-security-class-a"],
                        "company_ids": ["synthetic-company"], "mapping_status": "unavailable"}]
    with pytest.raises(ValueError, match="unverified"):
        provider_requests(manifest, include_unavailable=True)


@pytest.mark.parametrize("second", [
    security("SYNTH.B"),
    security(security_id="second-security"),
    security("SYNTH.B", security_id="second-security", company_name="Conflicting Company"),
    security("SYNTH.B", security_id="second-security", company_id="second-company"),
    security("SYNTH.B", security_id="second-security", company_id="second-company", cik="7654321",
             provider_symbol="SYNTH.A"),
])
def test_duplicate_or_conflicting_identities_are_rejected(second):
    with pytest.raises(ValueError):
        freeze_universe([security(), second], receipt())


def test_public_summary_has_only_aggregate_and_hash_evidence():
    manifest = freeze_universe([security()], receipt(), index_name="private-source-label")
    summary = public_universe_summary(manifest)
    assert summary["mapping_status_counts"] == {"unavailable": 0, "unverified": 1, "verified": 0}
    encoded = json.dumps(summary)
    for private in ("source_url", "example.org", "security_id", "synthetic-security", "company_id",
                    "mapping_evidence", "private-source-label"):
        assert private not in encoded


def test_immutable_write_and_offline_load_are_idempotent_and_read_only(tmp_path):
    manifest = freeze_universe([security()], receipt())
    target = tmp_path / "private" / "universe.json"
    assert write_universe(manifest, target) == target
    original_bytes, original_mtime = target.read_bytes(), target.stat().st_mtime_ns
    assert write_universe(manifest, target) == target
    assert load_universe(target) == manifest
    assert target.read_bytes() == original_bytes and target.stat().st_mtime_ns == original_mtime
    assert target.stat().st_mode & 0o077 == 0
    changed = freeze_universe([security()], receipt(raw_sha256="0" * 64))
    with pytest.raises(ValueError, match="Immutable"):
        write_universe(changed, target)
    assert target.read_bytes() == original_bytes
    with pytest.raises(FileNotFoundError):
        load_universe(tmp_path / "missing.json")
    assert not (tmp_path / "missing.json").exists()


@pytest.mark.parametrize("change", ["hash", "count", "unused_company", "duplicate_company", "security", "version"])
def test_load_rejects_content_and_structural_tampering(tmp_path, change):
    manifest = freeze_universe([security()], receipt())
    if change == "hash":
        manifest["manifest_sha256"] = "0" * 64
    elif change == "count":
        manifest["security_count"] = 500
    elif change == "unused_company":
        manifest["companies"].append({"company_id": "unused", "company_name": "Unused", "cik": None})
    elif change == "duplicate_company":
        manifest["companies"].append(deepcopy(manifest["companies"][0]))
    elif change == "security":
        manifest["securities"][0]["provider_symbol"] = "OTHER"
    else:
        manifest["schema_version"] = "invented_v0"
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_universe(target)


@pytest.mark.parametrize("content", [b'{"schema_version":"v1","schema_version":"v2"}', b'{"unexpected":NaN}'])
def test_load_rejects_duplicate_fields_and_nonfinite_json(tmp_path, content):
    target = tmp_path / "invalid.json"
    target.write_bytes(content)
    with pytest.raises(ValueError):
        load_universe(target)


def test_validate_returns_an_independent_copy():
    manifest = freeze_universe([security()], receipt())
    copy = validate_universe(manifest)
    copy["securities"][0]["security_name"] = "Changed"
    assert manifest["securities"][0]["security_name"] == "Synthetic Class A"


def test_freeze_cli_outputs_only_summary_and_exact_gate_precedes_write(tmp_path):
    records, source = tmp_path / "records.json", tmp_path / "source.json"
    records.write_text(json.dumps([security()]))
    source.write_text(json.dumps(receipt()))
    output = tmp_path / "manifest.json"
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    command = [sys.executable, str(root / "examples" / "freeze_universe.py"), "--records-json", str(records),
               "--source-receipt-json", str(source), "--output", str(output)]
    blocked = subprocess.run([*command, "--require-exact"], capture_output=True, text=True, env=env, check=False)
    assert blocked.returncode != 0 and not output.exists()
    accepted = subprocess.run(command, capture_output=True, text=True, env=env, check=True)
    manifest = load_universe(output)
    assert json.loads(accepted.stdout) == public_universe_summary(manifest)
    assert str(tmp_path) not in accepted.stdout and "example.org" not in accepted.stdout
