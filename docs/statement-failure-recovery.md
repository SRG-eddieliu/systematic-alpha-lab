# Statement failure diagnosis and offline recovery

This workflow preserves the closed collection baseline and creates a separate
version for recoverable statement rows. It uses the existing snapshot store,
normalizer and `OfflineDataReader`; it does not refresh the original batch.
The [collection contract](shared-pipeline-collection.md) and
[shared data contract](shared-data-contract.md) remain applicable.

## Closed baseline and raw audit

The original frozen scope contains 1,509 statement jobs. Its closed baseline
has 1,394 successful jobs and 115 failed jobs, with no pending, inflight or
uncertain jobs. The final failures are 109 `data_quality` jobs and six
`response_format` jobs. Five provider notices occurred earlier and were
recovered by explicitly selected retries; they are cumulative failure events,
not five additional final failed jobs. The original failure ledger, successful
pins, raw objects and collector fingerprints remain unchanged.

An independent offline audit verified all 109 data-quality raw objects against
the catalog and final receipts, reproduced their original rejection, and
inspected each annual and quarterly row:

| Rows | Annual | Quarterly | Total |
| --- | ---: | ---: | ---: |
| Original source rows | 1,915 | 7,412 | 9,327 |
| Invalid reported currency | 182 | 1,022 | 1,204 |
| Rows passing the existing structural checks after isolation | 1,733 | 6,390 | 8,123 |

Every invalid currency is the literal string `"None"`. No currency key is
absent, JSON null, blank or another malformed value in this cohort. The other
observed currencies are USD and EUR. The original normalizer checks for a
nonmissing uppercase three-letter string; that format check does not in
general certify membership in an ISO currency registry.

All 1,204 invalid-currency rows contain at least one finite amount. None is an
all-amounts-missing placeholder. Invalid rows span 2002 through 2026, including
63 rows in 2026; they cannot be dismissed as empty historical remnants.
Sixty-seven jobs were rejected because of exactly one invalid-currency row.
Every audited job retains rows in both annual and quarterly tables. The 8,123
retained original rows pass an in-memory replay of the existing normalizer
when the invalid rows are explicitly isolated. This is evidence for a partial
recovery candidate, not a claim that the missing rows have been repaired.

The exact private audit records source row positions, raw currency values,
dates, amount-status counts and source fingerprints without emitting financial
amounts. Its SHA256 is
`3e47b183912914d45b3493a566c95cc32623524ac40d169a00c94bbcf3479b16`.
The audit used a read-only immutable SQLite connection, blocked network
connections and verified source hashes, sizes, modification times and file
inventory before and after the read.

## A separate currency-quarantine version

The recovery normalizer retains valid rows verbatim and records rejected
currency rows in a separate quarantine output linked to their exact raw
source and row positions. It preserves the original raw response, including
the currency string and financial amounts in each rejected row. The recovery
uses its own normalizer version and manifests; it does not overwrite the
original `av_fundamentals_v1` datasets or turn the original 115 failures into
successful jobs in their original ledger.

Do not fill `"None"` with USD, copy an adjacent row's currency, or infer it
from a company's location or other statements. Some retained source histories
contain both EUR and USD, so even valid rows must retain their own currency.
The quarantine output is available for a later evidence-based correction; its
amounts are not certified for cross-row arithmetic while currency is unknown.

This recovery isolates a specific currency defect. Unexpected source shape,
period errors, duplicate periods, future periods and other original structural
violations must still fail closed. Amount values remain provider values;
normalization does not establish their units or accounting definitions. It
does not certify standalone-quarter versus YTD flow basis, fiscal-period
semantics, historical filing availability, stable company/security identity,
or research eligibility. Those checks belong to the consuming study.

## Run with a closed source and a new output root

All variables below are private path, run-ID or commit placeholders. Resolve
them outside the repository. Keep the source catalog closed throughout the
copy and verification, and choose a previously absent independent output
root. Do not run against a collector's active data root.

```bash
PYTHONPATH=src python examples/recover_currency_statements.py \
  --source-root "$SRG_CLOSED_SOURCE_ROOT" \
  --output-root "$SRG_RECOVERY_OUTPUT_ROOT" \
  --run-id "$SRG_SOURCE_RUN_ID" \
  --universe "$SRG_UNIVERSE_MANIFEST" \
  --code-commit "$SRG_CODE_COMMIT"
```

The CLI takes the explicit closed source and frozen batch scope, creates a new
closed copy, and performs recovery in that independent root. Its verification
must bind the code commit and source hashes, universe and original batch
fingerprints, exact raw observations, new normalized/quarantine manifests and
row counts. Inventory and hash/mtime checks must prove that the original
source is unchanged. Complete replay through `OfflineDataReader` must use the
new exact pins with network access blocked and credentials unavailable.

Use the emitted recovery coverage and verification result to determine the
actual output count. The audit's 109 candidate jobs do not substitute for a
completed recovery run. Keep full selections, row identities, quarantine
content, machine paths and raw receipts private; publish only aggregate counts
and allowed fingerprints. Read the new root only after all writing has ended.

## Bounded provider diagnostics

Separate, explicitly bounded diagnostic calls examined the six remaining
source-format failures. Six fresh statement requests returned HTTP 200 with
the exact two-byte body `{}`. Each response was archived before JSON validation
in a new diagnostic root, with its UTC request/response times, HTTP status,
body length and SHA256. These are new observations. The eight historical
response bodies remain recorded as not retained; no historical receipt or
raw object is reconstructed.

Two company-name searches returned five candidates on foreign venues; none
was accepted as an alias for the frozen US security scope. Three separate
company-overview requests, including one explicitly tested historical-symbol
hypothesis, also returned HTTP 200 with `{}`. No alternative symbol was used
for statement collection and no identity bridge was inferred from a similar
name. These observations establish a coverage gap at the tested endpoints and
observation time; they do not prove permanent provider unavailability.

The recovery diagnostics used 11 new calls: six statements, two name searches
and three overviews, with no implicit retries. The original collector used
1,505 attempts. Combined accounting for these two phases is 1,516 against the
declared 1,530 ceiling, leaving 14 attempts; the original batch counter is not
rewritten. Earlier identity preflight and entitlement-probe calls have their
own auxiliary accounting. No new purchase, credential rotation or fallback
security is part of this recovery. A further request requires a concrete
remaining hypothesis, an explicit selection and budget, and a separate receipt.

## Acceptance evidence

The closed execution on 2026-10-23 used code commit
`29d5541ce5a57bfaa6a8cae1f1b6579a60478798` and normalizer
`av_fundamentals_currency_quarantine_v1`. Its fixed
[aggregate receipt](validation-statement-failure-recovery-2026-10-23.json)
binds the parent and recovery manifests, selection, code, policy, inventories
and private verification files.

| Result | Count |
| --- | ---: |
| Original successful jobs, preserved | 1,394 |
| Failed jobs with accepted rows recovered | 109 |
| Jobs still without usable data | 6 |
| Newly readable annual / quarterly rows | 1,733 / 6,390 |
| Source rows preserved in quarantine | 1,204 |
| Securities with all three statements readable | 501 |
| Securities with quarantined periods | 46 |

The 501 readable securities do not have certified complete histories. The
remaining two securities have six empty source responses. The original ledger
continues to record its 115 failures; only the separate derived version has
1,503 usable statement jobs.

With network and credential loading blocked, execution wrote only the new
output root. After closure, independent all-pin replay verified 3,006 financial
tables / 141,303 financial rows. Quarantine and normalization audit outputs
bring the selected total to 3,224 tables / 142,725 rows; those diagnostic rows
are excluded from financial coverage. Every recovered or quarantined source
row was checked against its original array position and values, including
source types and per-row currency. All 4,322 parent and 4,762 derived input
files retained their bytes and modification times during verification.

The local suite passed 992 tests. Python 3.10/3.11
[CI on the implementation commit](https://github.com/SRG-eddieliu/systematic-alpha-lab/actions/runs/39962196462)
passed, including its configured examples. Independent review added regression
guards for numeric precision/type coercion and empty or incomplete receipt
table sets. Units, accounting semantics and historical research eligibility
remain unverified.
