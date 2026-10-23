# Beneish required-field audit and pipeline handoff

PR [#17](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/17) is merged.
Its reviewed head passed 757 local tests, the two public arithmetic examples and
Python 3.10/3.11 CI. The annual calculator is implemented; the source inputs still
need accounting and metadata acceptance. This follow-up audits the fresh Alpha
Vantage collection, without comparing or reusing legacy observations.

## Collection scope

This is a **fixed completed prefix of a running collection**, not a full S&P 500
result. The planned universe has **503 provider securities from an ETF-holdings
proxy**: 501 directory-verified symbols and two unverified candidates. Directory
recognition does not certify index membership or a stable issuer/company link.
Exact current S&P 500 membership remains unverified.

| Task state at the fixed checkpoint | Count |
| --- | ---: |
| Planned, three endpoints per security | 1,509 |
| Succeeded | 397 |
| Failed | 40 |
| Inflight | 1 |
| Pending | 1,071 |
| Securities with all three endpoints succeeded | 128 |

The audit selects all 397 succeeded tasks, covering 139 distinct provider symbols
and 794 annual/quarterly tables. Endpoint denominators differ: income statements
cover 131 symbols, balance sheets 134 and cash flows 132. These counts include
partial statement coverage; they are not a 139-company research panel. Failures
are reported separately: 34 normalization rejections for missing/unsupported
currency and six response-format failures without a successful raw statement pin.
Neither the failures nor the pending jobs appear in the successful-table field
rates. Collection order and normalization rejection can bias this partial sample.

The [aggregate receipt](validation-beneish-field-gaps-2026-10-22.json) is the
machine-readable evidence. A closed independent copy was rematerialized from
explicitly pinned immutable raw observations. Raw bytes and all original staged
tables were checked; copied tables matched except for their new local snapshot
identifier. The active collector catalog was never opened. All 1,191 selected
original files and all 1,192 closed-copy files retained their hashes and mtimes.
The read used blocked network access, zero provider calls and no credential read.
Exact source lineage and integrity fingerprints remain in private run records.

## Required annual fields

Counts are **finite decimal source values / rows in that endpoint**, before
cross-statement alignment, year pairing, positive-domain checks or semantic
acceptance. A zero or negative value counts as finite but can fail the model's
input rules. No field below is certified just because it is numeric.

| Canonical input | AV candidate | Finite annual rows | Finite quarterly rows | Remaining gate |
| --- | --- | ---: | ---: | --- |
| Sales | IS `totalRevenue` | 2,504 / 2,504 | 10,045 / 10,049 | Sales scope; negative inputs occur |
| COGS | IS `costofGoodsAndServicesSold` | 2,500 / 2,504 | 10,022 / 10,049 | Cost scope; negative inputs occur |
| Pure depreciation | IS `depreciation` | **0 / 2,504** | **0 / 10,049** | All values are missing markers |
| SG&A | IS `sellingGeneralAndAdministrative` | 2,388 / 2,504 | 9,653 / 10,049 | Scope and strictly positive domain; zeros occur |
| IBEI | IS `incomeBeforeExtraordinaryItems` probe | **0 / 2,504** | **0 / 10,049** | Column absent; no certified direct mapping |
| Net trade receivables | BS `currentNetReceivables` | 2,552 / 2,577 | 10,176 / 10,333 | Broader receivables scope; negative inputs occur |
| Current assets | BS `totalCurrentAssets` | 2,564 / 2,577 | 10,271 / 10,333 | Scope and positive domain |
| Current liabilities | BS `totalCurrentLiabilities` | 2,571 / 2,577 | 10,279 / 10,333 | Scope and positive domain |
| Total assets | BS `totalAssets` | 2,572 / 2,577 | 10,286 / 10,333 | Scope, residual-asset domain |
| Net PPE | BS `propertyPlantEquipment` | 2,270 / 2,577 | 8,615 / 10,333 | Net-PPE equivalence and positive domain |
| Noncurrent long-term debt | BS `longTermDebtNoncurrent` | **0 / 2,577** | **0 / 10,333** | All values are missing markers |
| Operating cash flow | CF `operatingCashflow` | 2,523 / 2,524 | 10,095 / 10,118 | Period and consolidated-scope consistency |

All three direct blocking fields have zero finite values in both annual and
quarterly selections. The auditor **does not calculate M or count eligible
pairs**. These gaps preclude accepting this prefix as strict annual-model inputs.
The earlier closed three-security adapter pilot separately returned zero scores.

## Accounting decisions

**Pure depreciation stays missing.** IS D&A is finite in 2,468/2,504 annual rows;
CF DD&A in 2,511/2,524. Those aggregates include amortization and/or depletion.
The AV dictionary describes its IS D&A as a nonproduction expense while CF DD&A
is a total. Subtracting the two does not isolate pure depreciation. Accumulated
D&A is a stock, so its change also needs a complete disposals/FX/reclassification
bridge. A future derivation needs complete component evidence for the same period,
entity and recognition scope; no existing aggregate is an automatic substitute.
See the [AV field dictionary](https://documentation.alphavantage.co/FundamentalDataDocs/gaap_documentation.html)
and [FASB presentation guidance](https://xbrl.fasb.org/impdocs/CNE_TIG/Consolidatedandnonconsolidatedentities.htm).

**Noncurrent debt has a conditional candidate, not an accepted fill.** AV maps
`longTermDebt` to total `LongTermDebt`; the cited FASB definition includes current
and noncurrent amounts. AV describes `currentLongTermDebt` as the current portion.
Therefore their difference is
worth reviewing when both scopes, dates, units and measurements agree. In this
prefix the two are jointly finite in **1,313 annual rows**: 1,211 have a nonnegative
difference and **102 a negative difference**. Quarterly counts are 4,470 jointly
finite, 4,108 nonnegative and **362 negative**. A nonnegative difference alone
does not verify equivalence. Do not floor negative differences, fill absent
current portions with zero, subtract broad `currentDebt`, or add total long-term
debt to current liabilities and double-count current maturities. Noncurrent
finance-lease obligations are a separate scope question. The strict adapter
continues to require its reviewed direct mapping; accepting a derivation would
need a separately reviewed contract change and source-bound evidence.
[AV definitions](https://documentation.alphavantage.co/FundamentalDataDocs/gaap_documentation.html)
and [FASB total long-term-debt definition, printed p.365](https://storage.fasb.org/US-GAAP-ReleaseNotes-2012-01-31Final.pdf#page=369)
support the candidate decomposition, not automatic acceptance of provider values.

**IBEI and trade receivables need semantic evidence.** `netIncome` and
`netIncomeFromContinuingOperations` do not automatically establish IBEI; the
bridge must resolve extraordinary/discontinued operations, attribution and the
scope shared with CFO. Elimination of the US GAAP extraordinary category does
not certify this provider's historical field mapping. Similarly,
`currentNetReceivables` can include notes, loans and other receivables; being a
nonfinancial company is insufficient evidence of net trade equivalence.
See [FASB ASU 2015-01](https://storage.fasb.org/ASU%202015-01.pdf#page=7),
[ASU 2014-08](https://storage.fasb.org/ASU%202014-08.pdf#page=23) and the
[AV dictionary](https://documentation.alphavantage.co/FundamentalDataDocs/gaap_documentation.html).

## Metadata and acceptance order

Across **38,105 source rows**, `asset_id` and `available_at` have zero nonempty
values; `period_start` and `fiscal_year` columns are absent. Amount-unit status is
unverified throughout. Income/cash-flow basis is unverified, while balance-sheet
basis is stock. The audit found no missing, invalid or duplicate period-end labels
within each selected source table. That check does not prove full-year durations,
fiscal-year continuity, cross-statement alignment or historical availability.

1. Finish or explicitly close the collection with a pinned success/failure ledger;
   retain the proxy-universe label until membership and issuer links are reviewed.
   Classify currency/response failures before deciding on an explicit retry batch.
2. Produce a per-required-field feasibility decision using AV evidence. Resolve
   pure depreciation first; review the 102 negative annual debt decompositions
   and the IBEI/trade-scope bridges. If AV cannot supply a required concept, keep
   strict Beneish blocked. Any alternative score needs a separately named method
   and validation; it must not silently inherit this definition.
3. Establish issuer identity, actual annual windows/fiscal years, unit scales,
   reporting/accounting scope and source-bound mapping evidence. Then run the
   existing annual adapter on an explicitly closed selection with reviewed context.
   Timing and universe history are additional gates before empirical market tests.

## Reproduce

The full local suite passed **794 tests**, including 37 new synthetic audit cases.
Ruff E4/E7/E9/F/I and diff checks passed. Independent review found no material
code/CLI issue; its forbidden-network synthetic run also preserved source hashes
and mtimes. These checks validate the audit implementation and rejection paths,
not the source concepts or full-universe completeness.

```bash
pytest -q tests/test_beneish_field_audit.py
python examples/audit_beneish_field_coverage.py \
  --data-root /private/closed-snapshot-root \
  --selection /private/pinned-field-audit-selection.json
```

To rerun the public notebook from the repository root:

```bash
python -m pip install nbformat nbclient ipykernel
jupyter execute notebooks/beneish_field_gaps_2026_10_22.ipynb --kernel_name=python3
```

The selection is a private JSON list of exact
`{"symbol": "...", "function": "INCOME_STATEMENT", "snapshot_id": "..."}`
objects, with at most one choice per symbol/function. Both annual and quarterly
tables must exist for every choice. The auditor uses the existing
`OfflineDataReader.read` integrity checks and rejects incomplete or mismatched
reads. It never discovers latest snapshots, opens the active collector catalog,
collects, writes inputs, joins statements or fills fields. Its output has only
aggregate counts and fixed policies. Unknown status labels are bucketed as
`other`, avoiding private-label leakage.

Row buckets distinguish absent columns, null/empty/None/null markers, invalid
numbers, booleans, nonfinite numbers and finite decimals. NaN/Infinity are
nonfinite, not zero; a missing source key already materialized as numeric NaN
cannot be distinguished from a native NaN at this layer. Decimal finiteness is
not float-calculator eligibility. The selected source rows remain the denominator
even when a candidate field has no usable values.

The [executed companion notebook](../notebooks/beneish_field_gaps_2026_10_22.ipynb)
recomputes the public summary tables from the aggregate receipt without credentials
or private data. All four code cells executed successfully and their saved table
counts were checked. Rendered visual QA was not completed because the local-file
preview was blocked by the browser protocol policy. Recomputing source coverage
itself still needs the authorized
closed snapshots and private selections; the public receipt cannot authenticate
the underlying private source lineage on its own.
