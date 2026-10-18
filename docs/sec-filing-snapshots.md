# SEC filing and financial-fact snapshots

This shared connector extends the [snapshot pipeline](data-snapshot-pipeline.md).
It stages source evidence for financial research. It does not certify a historical
market dataset. Examples and automated checks use explicitly synthetic entities.

## Source collection

`SECClient` uses only `https://data.sec.gov` and accepts three explicit requests:
company submissions, companyfacts, and a named submissions-history file for the
same zero-padded CIK. It requires a caller-supplied organization/contact User-Agent,
rejects redirects and failed/mismatched JSON responses, and sanitizes errors.
Contact headers are excluded from catalog requests and dataset provenance; echoed
contact details are rejected before storage. No default contact is invented.

Collection uses a preflighted total request budget, TTL cache, immutable raw
observations and zero-network replay through `SnapshotStore`. Calls are serial,
defaulting to 0.5 seconds apart with a minimum of 0.2 seconds; this applies to one
client/process. Concurrent processes need a shared rate coordinator. No automatic
retries, alternate hosts, rotating identities or unbounded history crawling exist.

The [SEC API guide](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
describes these endpoints and the additional history files listed in submissions.
Its companyfacts aggregates cover standard taxonomy/entity-wide facts; custom
concepts and richer filing contexts may require the original filing documents.
The [SEC developer guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions)
specifies declared contact headers and a 10 requests/second maximum. The public
service does not require an API key. No paid service or cloud provisioning is
needed by this implementation.

## Financial and timing contracts

`replay_sec_facts(store, facts_record, submissions_record, ...)` requires matching
CIKs, explicit namespace/tag pairs and optional history snapshots listed by the
submissions snapshot. Defaults select US GAAP Assets, NetIncomeLoss and
NetCashProvidedByUsedInOperatingActivities. A missing concept fails rather than
being silently replaced by a different accounting definition.

- Preserve all selected accession/unit/start/end observations, including repeated
  contexts and later filings for an older period. Never collapse to the latest
  value or choose a calendar frame as the fiscal period.
- Preserve the JSON numeric representation as `value_text`, its source unit and
  inclusive duration days. Raw bytes remain the authority for numeric encoding.
  A six-month cash-flow fact remains a six-month fact; no quarterly subtraction
  or currency/scaling conversion is performed.
- `source_fy` and `source_fp` belong to the source filing. They are not inferred
  fiscal labels for every comparative fact in that filing.
- Join submission metadata by exact accession. Mismatched filing date/form and
  overlapping accession histories fail. Unmatched facts remain visible with
  `filing_metadata_status=missing_history`; recent submissions are not presumed
  to include every old accession.
- Preserve the original acceptance string. Convert an explicit source timezone
  offset to `accepted_at_utc`; leave naive timestamps unconverted. Acceptance
  metadata is not verified public dissemination time. `available_at` remains
  missing for every staged fact.
- CIK identifies a filer/entity. It does not establish a stable traded-security
  identifier, historical ticker mapping or investible universe.

The SEC notes that acceptance and public availability can differ and that there
is no guaranteed dissemination lag. Neither a filed date, acceptance time nor a
current companyfacts download proves the original vintage was available for a
historical trading decision. Original filing inspection, amendment handling and
an explicit execution policy remain necessary.

`select_sec_context` requires an exact accession, namespace, tag, unit and start/end
contract and returns exactly one row. Missing or repeated matches fail. The caller
must decide what accounting definition and period the study actually needs.

## Local use

```bash
# No network, account, contact information or real company inputs.
PYTHONPATH=src python examples/sec_snapshot_demo.py

# Online mode reads SEC_USER_AGENT from the caller's environment.
# Supply a contact identity authorized for disclosure to SEC in that header.
# Use explicit CIKs and a private data root outside the repository.
PYTHONPATH=src python examples/ingest_sec_snapshots.py \
  --data-root /path/to/private/sec-data --ciks VERIFIED_CIK --max-requests 2

# Cached replay does not read SEC_USER_AGENT or create a network client.
PYTHONPATH=src python examples/ingest_sec_snapshots.py \
  --data-root /path/to/private/sec-data --ciks VERIFIED_CIK --offline --max-requests 0
```

Replace `VERIFIED_CIK` with an independently verified numeric CIK. For a history
extension, collect an explicit `sec_request` with
`kind="submissions_history"` and the listed filename, then pass its observation in
`history_records`. Collection does not automatically download every listed file.

Derived manifests bind all input snapshot IDs/hashes/times, the concept set and
normalizer source hash. A dependency change creates a distinct derived version;
replay verifies raw and Parquet hashes even when a cached dataset exists. Full
source payloads allow financial taxonomy names containing “Key” while still
rejecting named credential fields; request metadata retains its stricter guard.

## Validation status and next boundary

Synthetic tests cover fixed paths, rate pacing, sanitized failures, contact
requirements, total budgets, expiry, immutable observations, corrupted caches,
duration/unit separation, ambiguous contexts, missing/overlapping histories,
conflicting metadata and unverified availability. The offline example is runnable.
The full local suite passed **213 cases**, including **57 new SEC/source-guard
cases**, on Python 3.11.14. The CLI offline path also completed with two cached
synthetic observations while ignoring an intentionally invalid contact environment
value.

Live SEC retrieval and cross-provider statement reconciliation have not been
completed or certified in this slice. No actual SEC payloads or vendor-derived
comparison outputs are published here. The next validation is one bounded company
sample: verify CIK identity, match individual accessions and accounting concepts,
then compare annual and exact-duration cash-flow/income/asset amounts. Do not attach
SEC timing metadata to an Alpha Vantage value merely because period ends match.
