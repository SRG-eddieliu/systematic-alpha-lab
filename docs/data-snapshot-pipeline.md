# Shared data snapshots: first implemented slice

Prepared/executed: 2026-10-18. This is shared infrastructure inside Systematic
Alpha Lab. It supports multiple research modules without creating a new product
for each dataset. Public examples and tests are synthetic; actual inputs, access
receipts and credentials are retained privately.

## Implemented scope

| Layer | Implemented behavior | Boundary |
| --- | --- | --- |
| Provider | Hardened Alpha Vantage REST adapter; three fundamental-statement functions | No paid subscription purchase, live-market entitlement or commercial licence is inferred |
| Raw observations | Exact JSON response bytes, SHA-256 content-addressed storage, separate timestamped captures | Retrieval time records when this system observed data, not original filing availability |
| Catalog | SQLite request/observation ledger; no API keys in request metadata | Local single-process collection; no global account quota service or distributed scheduler |
| Normalized staging | Immutable annual/quarterly Parquet tables, manifests, hashes and normalizer source signature | Provider amount strings retained; units, flow basis, stable IDs and historical release times remain unverified |
| Research datasets | Source contracts and existing availability checks | Historical-universe reconstruction, source-version resolution and real-data factor certification remain separate work |

The first collection path accepts explicit symbols and `INCOME_STATEMENT`,
`BALANCE_SHEET`, `CASH_FLOW`. It does not need WRDS credentials, fetch constituents
or repeat a current membership list across historical dates. A symbol is recorded
as `provider_symbol_unmapped`, not fabricated into a PERMNO/CIK/company identifier.

## Collection, caching and replay

1. Preflight the entire plan against an explicit per-invocation request budget.
   Cached observations default to a maximum age of 24 hours. Over-budget plans
   fail before any API call. Account-level remaining allowance is not discovered.
2. Collect serially with a configured interval (default 15 seconds). Provider
   `Information`, `Note` and `Error Message` objects are failures even at HTTP 200.
   Stop on failure without automatic retries or switching keys.
3. Publish exact successful JSON bytes with atomic no-overwrite file creation.
   Identical bytes share a content-addressed object; separate observation records
   still preserve distinct collection times. A new response never replaces an old one.
4. Validate report shape, periods, symbol/currency and duplicate periods. Failed
   normalization leaves raw evidence but no registered normalized dataset. Never
   silently choose a duplicate version.
5. Save independent Parquet tables with a manifest binding the source hash,
   observation, normalizer ID/source signature, pandas version, table hashes and
   row counts. Replay verifies raw/table hashes. Source changes require a new
   normalizer version instead of silently reusing old outputs.

Hash verification detects corruption. A crash may leave unreferenced objects but
cannot register a half-published dataset as complete. This is a local reference
implementation, not a backup system, distributed catalog or full data warehouse.

The previous ingestion helper also restored out-of-range rows whenever filtering
returned an empty result. That fallback is removed; empty ranges stay empty,
fiscal-period filtering is explicit and caller-owned frames are not mutated.

## Time and financial semantics

- `period_end`: the provider's fiscal-period label, preserved alongside the original field.
- `observed_at`: actual response observation time in UTC.
- `available_at`: missing because the fundamental response has not supplied a
  verified filing/version availability timestamp. Never fill it from period end
  or silently use a download date as historical availability.
- `amount_unit_status`: unverified. `reportedCurrency` alone does not establish scaling.
- `flow_basis`: unverified for income/cash-flow amounts; balance-sheet values are
  stock observations. In particular, Alpha Vantage `operatingCashflow` is not
  automatically mapped to Compustat YTD `oancfy` or differenced again.
- No fiscal year/quarter is inferred from calendar months. Fiscal calendars and
  period/version mapping require their own evidence.

Raw snapshots collected today can support future first-observed analyses. They
do not recreate what an investor could have observed years earlier. Any use of
first-observed time needs an explicit research contract and execution policy.

## Run locally

```bash
# No credentials or network; temporary explicitly synthetic inputs.
PYTHONPATH=src python examples/fundamental_snapshot_demo.py

# Explicit local credential file; the key itself never goes on the command line.
# Keep the data root private and outside the source repository.
python examples/ingest_fundamental_snapshots.py \
  --data-root /path/to/private/srg-data --symbols IBM \
  --credentials /path/to/local/credential.yml --key-slot alphavantage_api_paid \
  --max-requests 3

# Alternative: ALPHAVANTAGE_API_KEY supplied by the caller's secret manager/environment.
# Reuse fresh cached inputs without loading credentials or making requests.
python examples/ingest_fundamental_snapshots.py \
  --data-root /path/to/private/srg-data --symbols IBM --offline --max-requests 0
```

Call `replay_fundamentals(store, record)` for a specific historical capture,
independent of the collection cache's freshness rule. Shared modules use snapshot
IDs/manifests rather than mutable per-symbol CSV files. Credentials, raw responses,
catalogs and generated tables are excluded from public GitHub publication.

## Source choice and remaining work

[Alpha Vantage's documentation](https://www.alphavantage.co/documentation/)
describes financial reports and market-data endpoints. Its free-key support page
currently states [25 requests per day](https://www.alphavantage.co/support/);
premium endpoint access and rate allowances depend on the actual subscription.
The [terms](https://www.alphavantage.co/terms_of_service/) classify use on behalf
of a corporation as commercial, for which a separate written arrangement is
required. A working key or a local setting named "paid" does not establish that
arrangement. No external communication or subscription action is performed here.

For historical financial-quality work, the next connector should preserve original
filing identities and timestamps. [SEC submissions and XBRL APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
provide a primary-source foundation without an API key; company-facts aggregates
still need careful accession, taxonomy, unit, duration and revision selection.
SEC financial frames align to calendar periods and are not a substitute for a
validated company fiscal calendar. SEC's [developer guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions)
requires a declared contact User-Agent and limits access to 10 requests/second;
acceptance timestamps and public dissemination time are not interchangeable.
This first slice does not implement or call a SEC connector.

Next stages are a verified identifier/filing-version connector, corporate-action
and price validation, research-dataset materialization, and then shared scheduling
and monitoring. Query engines/object storage can be added as volume warrants;
the initial local Parquet/SQLite path requires no cloud provisioning.

## Verification

Local full suite: **156 passed**, including 50 new collection/storage/error/time
cases. Environment: Python 3.11.14, NumPy 2.2.6, pandas 2.2.3, pyarrow 22.0.0,
requests 2.32.5, pytest 9.0.1. Tests cover HTTP-200 errors, sanitized credentials,
redirect rejection, immutable versions, hashes, corruption detection, schema
quarantine, unknown availability/units, cache expiry, budget preflight, zero-network
replay and the removed empty-filter fallback. Actual provider connectivity and
sample-data receipts are documented only in private research records. Hosted
Python 3.10/3.11 checks are verified separately after publication.
