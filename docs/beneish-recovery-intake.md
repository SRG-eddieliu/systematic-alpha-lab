# Audit-only intake of currency-quarantine statement recovery

Prepared 2026-10-23. The new materialization is accepted for **field-coverage
audit of the verified closed version**, not for the annual scoring adapter.
The [aggregate validation receipt](validation-beneish-recovery-intake-2026-10-23.json)
records provenance, exhaustive row partition, field coverage and execution checks.
The frozen Beneish definition and its semantic gates remain unchanged.

## Explicit mechanical support

`audit_beneish_field_coverage` now accepts an explicit common `normalizer` pin.
Its default remains `av_fundamentals_v1`, with the existing v2 report unchanged.
The only additional recognized label is
`av_fundamentals_currency_quarantine_v1`. Unknown or approximate labels reject
before a read. Recovery uses its own report version and marks the row basis as
currency-accepted source rows, not complete raw history or aligned research rows.

For each exact symbol/function/snapshot selection, only `annual` and `quarterly`
are requested. Metadata and row identities must match the selected normalizer.
Recovery rows also need the correct source array, unique nonnegative integer
ordinals, preserved reported currency and no diagnostic-only columns. Ordinal
gaps are allowed: quarantined positions must not be renumbered or filled.
Missing financial tables still fail; a diagnostic table is never a fallback.

The generic `OfflineDataReader` is unchanged. Its object/hash/dependency checks
do not certify a producer policy or accounting concept. This closed-version
acceptance additionally binds the handoff, original failed attempts, code and
policy, catalog/manifests and producer inventory. The new label alone does not
authenticate another dataset. The annual scoring adapter remains v1-only and
does not fall back to this materialization.

## Executed increment and preserved exclusions

The increment contains **109 statement selections / 46 provider securities**.
Original [1,394-success field evidence](beneish-source-feasibility.md) remains
separate; it was not rerun.

| Statement / table | Original source rows | Accepted financial rows | Quarantined rows |
| --- | ---: | ---: | ---: |
| IS annual | 694 | 645 | 49 |
| IS quarterly | 2,749 | 2,411 | 338 |
| BS annual | 631 | 562 | 69 |
| BS quarterly | 2,408 | 2,069 | 339 |
| CF annual | 590 | 526 | 64 |
| CF quarterly | 2,255 | 1,910 | 345 |
| **Total** | **9,327** | **8,123** | **1,204** |

All raw array positions are accounted for exactly once: accepted and quarantined
sets are disjoint and exhaustive. The private run checked **252,514 original
field values and types** in accepted rows, all quarantined full JSON records,
currency/reason/index preservation, and 218 normalization-audit rows against
provenance. Financial and diagnostic tables were read separately, 218 of each.
The field audit used the same cached financial tables checked by that partition.

The run held the existing shared lock, rejected active SQLite sidecars and used
read-only immutable/query-only access. All **4,762 root files and 82 external
dependencies** retained their bytes and modification times; executed research
code stayed fixed. Network/DNS/socket/HTTP, credential-loader and writable-store
constructor attempts were zero. No normalizer, collector or annual calculator
was invoked. Private pins, code fingerprints and full execution bindings remain
in authorized private evidence; this receipt publishes only safe aggregates.

## New coverage does not repair the accounting gaps

- Pure depreciation remains missing in all **645 annual / 2,411 quarterly IS
  accepted rows**. IBEI, amortization and depletion probes are absent.
- Direct noncurrent debt remains missing in all **562 annual / 2,069 quarterly
  BS accepted rows**. Total/current components are jointly finite in 306 annual
  rows, including 18 negative implied differences; quarterly counts are 948/57.
  Nonnegative arithmetic still does not establish composition or lease scope.
- CF `profitLoss` remains missing in all **526 annual / 1,910 quarterly rows**;
  the jointly finite income-comparison denominator remains zero.
- Period labels have no missing, invalid or duplicate counts here. That does
  not supply annual starts, fiscal years, verified issuer identity, units or
  publication timing. Those required metadata are absent or unverified.

Combined engineering readability is 1,503/1,509 jobs and 501 ETF-proxy securities
with three endpoints; 46 securities have quarantined periods. Six jobs for two
securities still lack usable data, and eight historical failed-response bodies
remain unavailable. Neither complete history nor exact S&P 500 membership is
certified. No M-score, eligible-pair count or investment result is reported.

## Source and method follow-up

The [pilot contract](av-primary-supplement-pilot-contract.json) fixes at most
three companies and two adjacent years, with engineering as sole collector.
Qualified nonmissing AV remains primary; SEC/issuer original disclosures address
key gaps and accounting review, while yfinance supplies quick candidates and
cross-checks. WRDS/Compustat access is excluded as a dependency; FMP remains a
future conditional candidate, with no paid service added. Actual supplemental
values are still unaccepted by this record. No blind fill, month-end matching,
assumed zero or numeric acceptance tolerance is permitted.

The [paper-target review draft](beneish-paper-target-review-draft.md) separates
technical reconciliation from the frozen v1 policy. Its proposed label is not
an executable definition. Supplement integrity, accounting equivalence,
historical availability and investment performance remain separate gates.

## Reproduce the public checks

```bash
pytest -q tests/test_beneish_field_audit.py tests/test_beneish_recovery_intake.py tests/test_beneish_pipeline.py
python examples/audit_beneish_field_coverage.py \
  --data-root /path/to/closed-recovery-root \
  --selection /path/to/private-selection.json \
  --normalizer av_fundamentals_currency_quarantine_v1
```

The CLI performs the pinned field audit; the separate private closure/partition
run supplies the stronger real-input evidence above. Synthetic tests require no
credentials or private data. Full local validation: **867 passed**, including
68 new cases and 121 focused old/new audit and adapter tests; Ruff E4/E7/E9/F/I
and diff checks passed. Independent schema/code and contract/privacy review found
no remaining blockers. The original normalizer's defaults and scoring rejection
behavior are covered by regressions.
