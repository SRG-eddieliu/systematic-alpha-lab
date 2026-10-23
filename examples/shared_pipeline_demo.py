"""Credential-free, zero-network demonstration of the shared statement pipeline.

All companies, source evidence, report amounts and dates below are synthetic.
The example.invalid evidence URLs are never fetched. Real verification must use
actual source evidence; this example does not establish index membership or
historical availability.
"""
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from systematic_alpha_lab.data_pipeline.alpha_vantage_rest import JSONResponse
from systematic_alpha_lab.data_pipeline.fundamental_batch import (
    create_fundamental_batch,
    fundamental_batch_summary,
    replay_fundamental_batch,
    run_fundamental_batch,
)
from systematic_alpha_lab.data_pipeline.snapshot_store import SnapshotStore
from systematic_alpha_lab.data_pipeline.statement_quality import profile_fundamental_receipts
from systematic_alpha_lab.data_pipeline.universe import (
    freeze_universe,
    load_universe,
    provider_requests,
    public_universe_summary,
    write_universe,
)


class SyntheticClock:
    def __init__(self):
        self.now = datetime(2001, 4, 2, tzinfo=timezone.utc)
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


class SyntheticClient:
    """Return local JSONResponse objects; no credential loader or HTTP adapter."""

    def __init__(self):
        self.calls = 0

    def fetch_json_response(self, function, params):
        self.calls += 1
        amounts = {
            "INCOME_STATEMENT": {"totalRevenue": "1000", "netIncome": "100"},
            "BALANCE_SHEET": {"totalAssets": "2000", "totalLiabilities": "500"},
            "CASH_FLOW": {"operatingCashflow": "120", "capitalExpenditures": "None"},
        }[function]
        payload = {
            "symbol": params["symbol"],
            "annualReports": [{"fiscalDateEnding": "2000-12-31", "reportedCurrency": "USD", **amounts}],
            "quarterlyReports": [{"fiscalDateEnding": "2001-03-31", "reportedCurrency": "USD", **amounts}],
        }
        return JSONResponse(payload, json.dumps(payload, sort_keys=True).encode())


def synthetic_universe():
    records = [{
        "security_id": f"synthetic-security-{suffix}", "company_id": f"synthetic-company-{suffix}",
        "security_name": f"Synthetic {suffix} Common Stock", "company_name": f"Synthetic {suffix} Company",
        "source_symbol": f"SYNTH.{suffix}", "provider": "alpha_vantage", "provider_symbol": f"SYNTH.{suffix}",
        "provider_symbol_status": "verified", "mapping_evidence": ["https://example.invalid/synthetic-mapping"],
    } for suffix in ("A", "B")]
    source = {
        "source_url": "https://example.invalid/synthetic-universe",
        "captured_at": "2001-04-02T00:00:00Z", "as_of": "2001-04-02",
        "raw_sha256": hashlib.sha256(b"explicitly synthetic universe source").hexdigest(),
        "kind": "secondary_index", "source_status": "unknown",
        "verification": {"status": "unverified", "scope": "unverified", "method": None, "evidence_urls": []},
    }
    return freeze_universe(records, source, index_name="Synthetic Example Universe")


def file_state(root):
    """Local comparison only; paths and source object identities are not printed."""
    return {path.relative_to(root): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def main():
    clock, client = SyntheticClock(), SyntheticClient()
    with TemporaryDirectory(prefix="shared-pipeline-synthetic-") as directory:
        root = Path(directory)
        universe_path = write_universe(synthetic_universe(), root / "universe.json")
        universe = load_universe(universe_path)
        symbols = [item["provider_symbol"] for item in provider_requests(universe)]
        store = SnapshotStore(root)
        run_id = "synthetic-statements"
        plan = create_fundamental_batch(
            store, run_id=run_id, symbols=symbols, universe_sha256=universe["manifest_sha256"],
            universe_scope="secondary_index", max_requests=3 * len(symbols), min_interval_seconds=1,
            clock=clock,
        )
        collected = run_fundamental_batch(
            client, store, run_id=run_id, max_requests=plan["config"]["max_requests"],
            clock=clock, sleep=clock.sleep,
        )
        assert collected["state"] == "complete"
        assert client.calls == len(plan["jobs"]) == 6
        calls_before_resume = client.calls
        resumed = run_fundamental_batch(None, store, run_id=run_id, max_requests=6, clock=clock, sleep=clock.sleep)
        assert resumed["state"] == "complete" and client.calls == calls_before_resume
        assert [job["pin"] for job in resumed["jobs"]] == [job["pin"] for job in collected["jobs"]]

        # Collection is now closed. Replay and quality use exact pinned receipts
        # with no client and must leave every existing file untouched.
        receipts = [{"request": job["request"], **job["pin"]} for job in resumed["jobs"]]
        before = file_state(root)
        replay = replay_fundamental_batch(root, run_id=run_id)
        quality = profile_fundamental_receipts(root, receipts)
        assert file_state(root) == before
        assert replay["replayed_tables"] == replay["replayed_rows"] == 12
        assert len(clock.sleeps) == 5 and all(seconds == 1 for seconds in clock.sleeps)
        amount_counts = Counter()
        for table in quality["tables"]:
            for counts in table["amount_fields"].values():
                amount_counts.update(counts)
        print(json.dumps({
            "input": "explicitly synthetic; not market or historical-vintage evidence",
            "network_requests": 0, "credentials_required": False,
            "universe": public_universe_summary(universe),
            "plan": {"symbols": len(symbols), "statements_per_symbol": 3, "planned_jobs": len(plan["jobs"]),
                     "min_interval_seconds": plan["config"]["min_interval_seconds"]},
            "collection": fundamental_batch_summary(collected),
            "fake_client_calls": client.calls, "repeat_resume_calls": client.calls - calls_before_resume,
            "simulated_pacing_sleeps": len(clock.sleeps),
            "replay": replay, "offline_files_unchanged": True,
            "quality": {
                "profile_version": quality["profile_version"], "profile_source_sha256": quality["profile_source_sha256"],
                "input_pins_sha256": quality["input_pins_sha256"], "tables": len(quality["tables"]),
                "rows": sum(table["rows"] for table in quality["tables"]), "amount_status_counts": dict(amount_counts),
                "available_at_supplied_rows": sum(table["available_at_supplied_rows"] for table in quality["tables"]),
                "stable_asset_id_supplied_rows": sum(table["stable_asset_id_supplied_rows"] for table in quality["tables"]),
                "amount_unit_statuses": sorted({status for table in quality["tables"]
                                               for status in table["amount_unit_statuses"]}),
                "flow_basis_statuses": sorted({status for table in quality["tables"]
                                               for status in table["flow_basis_statuses"]}),
                "eligibility": quality["eligibility"],
            },
        }, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
