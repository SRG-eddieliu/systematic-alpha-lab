# Shared data contract v1

Shared Data Pipeline owns the universe, provider collection, immutable storage,
normalization, quality controls and versioned offline access in
`systematic_alpha_lab.data_pipeline`. Financial Quality / Integrity research owns
factor definitions, Beneish and Adjusted M formulas, portfolio rules and research
validation. Research contracts are not changed by this document. Code is shared
through a pinned GitHub version and the existing SRG main progress Page; a second
pipeline or progress checkpoint is not created.

## Current universe and identity

`data_pipeline.universe` freezes explicitly supplied records. It does not fetch
constituents, establish source accuracy, infer identities, transform ticker
punctuation or assume 500 securities. Several share classes can belong to one
company, so security and company counts differ. A CIK is a company identifier;
it cannot be used as the security identity. The manifest keeps the company table
separate from the security table, including explicit share-class and exchange
labels when supported by evidence.

An unresolved issuer link has `company_id=null`, `company_name=null` and no CIK;
the source listing label remains `security_name`. The pipeline does not group
companies by similar names. If any issuer link is unresolved, `company_count`
is null. `identified_company_count` and `unresolved_company_security_count`
report the known portion and the unresolved security count without inventing
an issuer count.

The private source receipt requires:

| Field | Meaning |
| --- | --- |
| `source_url` | HTTPS source URL without credentials; raw source remains private |
| `captured_at` | Aware observation timestamp, canonicalized to UTC |
| `as_of` | Explicit membership date, no later than the UTC capture date |
| `raw_sha256` | SHA256 of exact captured source bytes |
| `kind` | `exact_index`, `secondary_index`, or `etf_proxy` |
| `source_status` | `current`, `stale`, or `unknown`; omission becomes `unknown` |
| `verification` | `status`, `scope`, `method`, `evidence_urls`, optional `notes` |

Verification status is `verified`, `unverified`, or `failed`. Scope is
`full_constituents`, `partial`, or `unverified`. Verified status requires a
recorded method and evidence URLs. An `exact_index` declaration additionally
requires current source status, verified status and full constituent scope.
These are evidence gates, not an independent check that a caller's assertions
are true. The source acquisition and validation step must support every claim.
No arbitrary age threshold makes a source current automatically.

Secondary sources and ETF holdings retain their source kind even after a check.
`require_universe_scope(manifest, require_exact=True)` rejects both kinds and
any stale or unverified exact claim. An ETF holdings list cannot be called an
accurate index list without a separately verified full constituent source.
This contract does not certify that any production S&P 500 list has been frozen.

Each supplied security record requires `security_id`, `company_id`,
`company_name`, `security_name`, `source_symbol`, `provider`, `provider_symbol`,
`provider_symbol_status` and `mapping_evidence`. Optional attributes are `cik`,
`share_class` and `exchange`. Provider mapping status is `verified`, `unverified`
or `unavailable`; verified status requires evidence URLs and unavailable status
requires a null symbol. For example, `BRK.B` and `BRK-B` are distinct explicit
mapping inputs. No rule silently converts one into the other. A response echoing
the requested symbol establishes request/response agreement, but does not by
itself establish a security's identity.

`provider_requests(manifest)` defaults to verified mappings and returns unique
explicit provider symbols, each linked to its security and company IDs. This
avoids duplicate company requests when a provider maps multiple share classes
to one symbol. Every security in the manifest must declare the requested
provider. If any row declares another provider, the entire plan fails; it does
not silently filter the universe. A desired subset requires an explicit
separate freeze with its own fingerprint. Unavailable mappings block the plan; an explicit
`require_verified=False` opt-in permits unverified mappings while preserving
their status. That opt-in does not satisfy an exact-index collection gate.
An additional `include_unavailable=True` opt-in returns each unavailable
security as an explicit blocked row with a null provider symbol; it does not
drop securities from a plan or make those rows requestable.

All v1 manifests have `membership_basis="current_only"`. Current membership
cannot establish historical membership or remove survivorship bias. The scope
gate rejects `historical=True` and any requested membership date different from
the receipt's explicit `as_of`. Source financial period labels do not turn a
current constituent list into a historical universe.

## Immutable input and collection boundaries

`freeze_universe` produces `srg_universe_v1`. Securities and companies are sorted
by their explicit IDs. The manifest fingerprint is SHA256 of UTF-8 JSON with
sorted keys, compact separators, preserved Unicode and no nonfinite numbers,
excluding only `manifest_sha256` itself. Reordering input records does not change
this fingerprint. A changed source, receipt, identity or provider mapping
creates a new fingerprint.

`write_universe` atomically creates a private manifest and refuses to replace a
different one. Writing identical bytes is idempotent. `load_universe` is offline
and read-only: it checks schema, content, counts, ordering, uniqueness and hash,
rejects duplicate JSON fields, and never downloads missing inputs.

The collector must pin this manifest fingerprint, an explicit request budget,
the three functions `INCOME_STATEMENT`, `BALANCE_SHEET` and `CASH_FLOW`, the
interval, retry policy, refresh mode and every reused receipt before execution.
The actual unique mapped symbol count determines request count; multiplying
500 by three is not an accepted plan. Existing successful pilot snapshots are
reused only when their pinned request and hashes verify. Refresh is an explicit
new collection action, with a new observation and immutable source object.
Credentials use the existing private loader. No purchase, key rotation, silent
source substitution or unbounded retry is authorized by this contract.

The default interval remains 15 seconds after the preceding response or error
completes, including across restarts and batches. This collection run explicitly
selected a 1.1-second minimum; an additional recorded transport policy waits
2 seconds after responses. A 1.1-second completion interval has an upper bound
of about 54.55 requests per minute, below the current
smallest [official paid plan](https://www.alphavantage.co/premium/) at 75 requests
per minute as checked on 2026-10-23 UTC. Paid-only endpoint access was observed
for the selected credential; its exact subscription tier and shared usage
remain unknown. A generic free-burst notice cannot establish that a credential
is not paid. Provider quota or entitlement notices halt collection. Requests
use a finite budget without a purchase or credential change. Permission to
redistribute provider data is not established by collection or this contract.

Collectors and readers must not concurrently mutate/read the same active
catalog. Close collection before replay, or explicitly use a closed independent
snapshot copy. `SnapshotStore` remains the sole raw/normalized object store;
`OfflineDataReader.catalog/read` remains the default read interface. Adding this
universe manifest does not create a second data pipeline.

## Alpha Vantage standardization and limits

The existing `av_fundamentals_v1` normalizer preserves source amount fields as
supplied, including financial amount strings and source missing-value labels.
It does not convert absent fields, empty values or `"None"` to zero. Research
numeric conversion must record its own field selection, parse failures,
required-field checks and exclusion policy.

| Field / state | Contract |
| --- | --- |
| `period_end` | Source `fiscalDateEnding`, checked as a source calendar label |
| `period_type` | Source array label `annual` or `quarterly`, not an inferred fiscal quarter |
| `currency` | Source `reportedCurrency`; no exchange conversion or comparability claim |
| `amount_unit_status` | `unverified`; amount scale is not silently assumed |
| `flow_basis` | Income and cash-flow reports remain `unverified`; balance sheet is labelled `stock` |
| `observed_at` | When this source response was observed by the collector |
| `available_at` | Null; full financial-statement release availability has not been established |
| `availability_basis` | `not_supplied` |
| `asset_id` | Null in the current normalizer; provider symbol is not promoted to a security ID |
| `identifier_basis` | `provider_symbol_unmapped`; explicit universe evidence is a separate pinned input |
| `snapshot_id`, `normalizer` | Exact source observation and normalization version |

Annual and quarterly arrays must not automatically be treated as YTD reports
and differenced. A quarter's fiscal period, reporting duration, units and cash
flow basis require source evidence before a research computation relies on
them. A fixed lag or an `EARNINGS.reportedDate` cannot establish the verified
availability of an entire income statement, balance sheet and cash-flow
statement. Source observations fetched today are current API vintages of
historical periods; they are not historical point-in-time vintages.

Schema conflicts, duplicate or missing periods, unsupported currencies and
request/response symbol disagreement preserve the immutable raw observation
but prevent normalized publication under the existing normalizer. Successful
collection, normalized publication, arithmetic eligibility, historical
availability and successful alpha validation are distinct states. Coverage
reports must state which state is counted and retain failures.

Current engineering gaps for the shared contract are verified complete index
membership, verified provider-to-security mappings, verified unit/scale and
duration semantics, verified fiscal quarter/year keys, full-statement
availability evidence and historical vintages/membership. The pipeline does
not fill these gaps using factor-specific assumptions. Research must declare
which gaps block each proposed calculation and backtest.

## Reproduce the freeze and publish evidence

Keep the captured raw source, explicit records, source receipt, full manifest,
provider raw snapshots and private execution receipts outside tracked public
artifacts. The following uses caller-supplied private paths; no credential is
needed and no network request is made:

```bash
python examples/freeze_universe.py \
  --records-json "$SRG_UNIVERSE_RECORDS" \
  --source-receipt-json "$SRG_UNIVERSE_RECEIPT" \
  --output "$SRG_UNIVERSE_MANIFEST"

# Use this flag only when the receipt meets the documented exact-index gate.
python examples/freeze_universe.py \
  --records-json "$SRG_UNIVERSE_RECORDS" \
  --source-receipt-json "$SRG_UNIVERSE_RECEIPT" \
  --output "$SRG_UNIVERSE_MANIFEST" --require-exact

python -m pytest -q tests/test_universe.py
```

The CLI prints only `public_universe_summary`: counts, source kind,
freshness/verification statuses, dates and content fingerprints. It omits row
identifiers, source URLs, private source labels, mapping evidence and local
paths. GitHub and external Pages may contain original code, tests, contract
documentation, allowed aggregate validation records and hashes. They must not
contain private raw data, credentials, private source identifiers or private
machine paths. Publication rights for a source are not implied by a successful
fetch. A reproducibility handoff pins code commit, configuration/input hashes,
normalizer, exact read selections, coverage/failures and offline replay result;
private manifests and raw evidence remain separately retained.
