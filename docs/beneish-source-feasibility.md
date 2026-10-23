# Alpha Vantage field feasibility and closed-input handoff

Prepared 2026-10-22 (America/Toronto). PR [#18](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/18)
was reviewed again at its exact head, passed 794 local tests and Python 3.10/3.11
CI, and merged. This follow-up uses the same frozen annual Beneish definition;
it extends diagnostics without accepting substitutions or calculating M.

**2026-10-23 addendum:** [target reconciliation, source alternatives and real
Drive sample recovery](beneish-source-options-2026-10-23.md) qualify the historical
expense/debt/income targets and update the recovery status. The counts below
remain evidence for the original closed collection, not the new engineering
currency-recovery version. The strict v1 contract is unchanged.

**Conclusion:** AV documents the correct pure-depreciation concept, but this
closed collection supplies no usable values for it. Noncurrent debt and IBEI
also remain blocked. More arithmetic cannot repair absent source concepts.

## Full planned scope, with failures retained

The collection has ended: **1,394 succeeded / 115 failed / 1,509 planned tasks**,
with zero pending, inflight or uncertain tasks. The planned 503 securities remain
an **ETF-holdings proxy**, not certified exact current S&P 500 membership or 503
verified companies. There are 455 securities with all three endpoints, 23 with
partial coverage and 25 with no accepted statement. Do not silently exclude the
48 securities with incomplete coverage.

Final failures comprise 109 data-quality rejections and six response-format
failures. Five earlier provider notices were retried successfully; they are not
five additional final failures. Eight historical failed-response bodies are
unavailable: two notice bodies were not recorded, and six response-format
attempts retained a body hash without the body. Declare all eight gaps in a
backup closure; do not claim the entire response history is recoverable. This does not alter
the selected succeeded-statement field counts. The producer batch remains labelled
incomplete because final failures remain, even though no requests are pending.

The research auditor read all 1,394 explicit succeeded pins: 2,788 tables,
133,180 source rows, 478 distinct provider securities. IS and BS each have 463
selected symbols, CF 468. Rates use their own endpoint/table rows, excluding the
115 failed tasks; historical coverage and rejection bias remain relevant.

The [aggregate receipt](validation-beneish-source-feasibility-2026-10-22.json)
records the results. Before opening the catalog, the research run matched the
producer's final closed inventory, rejected SQLite sidecars and acquired the
existing nonblocking shared lock. All **4,322 files** retained content and mtime
through the audit. Network, credential loading and writable-store construction
were blocked, with zero attempts. Nothing was re-captured or re-normalized.
Source pins, hashes, observed timestamps, raw amounts and paths remain private.

## Pure depreciation: documented, not supplied here

The [official GAAP dictionary](https://documentation.alphavantage.co/FundamentalDataDocs/gaap_documentation.html)
maps `depreciation` to tangible-asset depreciation, including production and
nonproduction expense. That is a suitable direct **concept candidate**, subject
to period, units, reporting scope and source verification. The
[provider overview](https://documentation.alphavantage.co/FundamentalDataDocs/index.html)
describes taxonomy-derived values as well as reported values; documentation alone
does not demonstrate per-company coverage or a usable observation.

| Probe | Annual finite / source rows | Quarterly finite / source rows | Raw-to-normalized finding |
| --- | ---: | ---: | --- |
| IS `depreciation` | **0 / 8,809** | **0 / 35,259** | Every raw value is a missing marker, preserved by normalization |
| BS `longTermDebtNoncurrent` | **0 / 8,892** | **0 / 35,592** | Every raw value is a missing marker, preserved by normalization |
| IS `incomeBeforeExtraordinaryItems` | **0 / 8,809** | **0 / 35,259** | Key absent from every raw row; no value invented |
| IS `amortization` / `depletion` probes | **0 / 8,809 each** | **0 / 35,259 each** | Both keys absent; no documented mapping is asserted for these probes |

The raw check aligned exact source periods and compared every named value or
absence with the normalized table. These source gaps were not introduced by a
normalizer fill/drop branch. This statement covers the succeeded selections;
it does not describe all possible AV issuers, products or future captures.

IS D&A has 8,718/8,809 finite annual values, and CF DD&A 8,876/8,924. Their
documented scopes differ: nonproduction D&A versus total DD&A. Their difference
does not isolate pure depreciation. Exact decomposition would need complete
same-scope amortization/depletion components and evidence; this collection and
current documented field set do not establish that bridge. Changes in net PPE,
accumulated D&A or EBITDA minus EBIT also do not establish the required concept.
No documented alternative AV endpoint was found that resolves it exactly.

The official IBM demo URLs for the three financial endpoints returned an
`Information` notice in this check, with no statement payload. They therefore
provide neither a usable-value example nor evidence that the demo's depreciation
is null. No account key was used. The reason for the actual collection's missing
values, plan entitlements and any future endpoint coverage remain unconfirmed.

## Noncurrent debt: review the composition before deriving

`longTermDebt - currentLongTermDebt` remains a conditional candidate. AV points to
total long-term debt, while the cited
[FASB definition, printed p.365](https://storage.fasb.org/US-GAAP-ReleaseNotes-2012-01-31Final.pdf#page=369)
explicitly includes current and noncurrent portions. That does not prove that
every provider observation implements a compatible decomposition.

| Same-row debt diagnostic | Annual | Quarterly |
| --- | ---: | ---: |
| BS source rows | 8,892 | 35,592 |
| Both components finite | 4,474 | 15,267 |
| Both components nonnegative | 4,474 | 15,267 |
| Total at least current portion | 4,158 | 14,026 |
| **Total below current portion** | **316** | **1,241** |

Negative differences occur even with nonnegative component amounts. They expose
a composition inconsistency, without identifying its cause. Do not floor a
negative difference, assume a missing current portion is zero, or subtract broad
`currentDebt`. `shortLongTermDebtTotal` is a broad total, not noncurrent LTD.

Accepting a derivation requires the same period, version, currency/scale,
consolidation and measurement; proof that the total includes exactly the current
maturities being removed; resolved lease scope; and source-bound review. A
nonnegative difference is only a numerical screen. The strict adapter still uses
its direct reviewed field contract; no derived debt is filled by this audit.

## IBEI: an income bridge remains absent

The current AV GAAP dictionary does not list the direct IBEI probe. Annual IS
`netIncome` has 8,799/8,809 finite values, continuing-operations income 6,824/8,809,
and tax expense 8,783/8,809. Their names and availability do not certify IBEI.

The new CF diagnostic compares `netIncome` and consolidated `profitLoss` within
the **same source row**, using exact finite Decimal equality. Here `profitLoss`
is missing in all 8,924 annual and 35,704 quarterly CF rows, so the jointly-finite
comparison denominator is **zero**. Zero observed differences is therefore not
agreement. Even an equal pair would not certify IBEI or explain attribution.

A bridge must resolve extraordinary/discontinued operations, parent versus
noncontrolling-interest attribution and the scope shared with CFO. Changes in
US GAAP do not by themselves certify a provider series against the selected
historical research concept. See [ASU 2015-01](https://storage.fasb.org/ASU%202015-01.pdf#page=7)
and [ASU 2014-08](https://storage.fasb.org/ASU%202014-08.pdf#page=23).
Before-tax income minus a tax field is not automatically an accepted bridge.

## Decision and bounded provider questions

Strict annual Beneish remains blocked for this closed input selection. The audit
calculates no factor or eligible-pair count. Across all source rows, stable issuer
identity and availability metadata remain empty, annual starts/fiscal years are
absent and units remain unverified. These gates survive any later amount repair.

Questions prepared for provider clarification, **not sent by this work**:

1. Is `depreciation` currently populated for these products, issuers and periods?
   What does its missing marker mean, and is availability tied to a specific
   documented product? Is there a source-tag/component explanation for a value?
2. Do the two long-term-debt fields form the same current/noncurrent decomposition
   in each period, including leases and restatements? How are negative implied
   noncurrent amounts reconciled?
3. Is there a documented IBEI/consolidated-income bridge with discontinued,
   extraordinary and attribution components on the same CFO reporting scope?

Retain missing values until evidence resolves these questions. If the provider
cannot establish a required concept, keep this definition blocked. An alternative
score needs its own name, formula and validation; this work does not switch
providers, assume an upgraded subscription fixes gaps or silently relax the method.

## Recovery is a separate acceptance gate

Independent review of the backup proposal and helper found value in preserving a
self-contained closed bundle: original catalog/raw/normalized objects plus batch,
universe, identity, receipts, lineage, code and environment. A same-disk copy and
successful offline reading do not establish an independent backup. Restoration
must preserve original IDs and bytes; capture/replay creates a new materialization.

The helper's independent synthetic seal/restore/verify test passed after the
original source path was made unavailable. That verifies a bounded local recovery
path. Full-bundle, OS-isolated and real cloud-download recovery remain separate
acceptance items. Baseline/closure records, a pinned recovery environment and
decryption-key recovery must survive loss of the working machine. This does not
require another pipeline. Existing [restic](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)
and [rclone backends](https://rclone.org/drive/) support the proposed tool approach;
service choice alone does not demonstrate a restorable backup.

Collection hands off closed inputs; backup preserves the bundle; research reruns
field and metadata gates through the original `OfflineDataReader`. Local source
analysis can continue while the independent backup trial proceeds. Do one complete
restore before adding multi-cloud, automatic retention or deletion machinery.

## Reproduce and validation

```bash
pytest -q tests/test_beneish_field_audit.py
python examples/audit_beneish_field_coverage.py \
  --data-root /private/closed-snapshot-root \
  --selection /private/final-source-selection.json
```

V2 adds component probes, broader-debt exclusions, debt-component sign counts
and same-row CF income comparison. It uses exact comparisons rather than float
conversion or Decimal subtraction, including extreme exponents. No canonical
field is filled and semantic status remains unverified. The old v1 receipt and
notebook remain the historical 397-task-prefix evidence, not the final-batch view.

Full local tests: **799 passed**, including 42 audit tests; Ruff E4/E7/E9/F/I and
diff checks passed. Independent code review found no material findings and checked
strict Decimal contexts, repeated indexes, missing values and source immutability.
The public receipt reproduces aggregate arithmetic; authenticating private source
lineage still requires the authorized private evidence.
