# Bounded supplement review: AAPL, MSFT and IBM

Reviewed 2026-10-23. Alpha Vantage remains primary where the observation is
nonmissing and concept-qualified. Original company reports provide useful debt,
receivables and income facts; this pilot does **not** establish a complete
pure-depreciation or paper DP14−AM65 mapping. No canonical supplemental field or
M-score is accepted by this review.

The scope is three companies × FY2024/FY2025, under the unchanged
[frozen collection contract](https://github.com/SRG-eddieliu/systematic-alpha-lab/blob/495c04b72f616156cc44458288555c6e0364c366/docs/av-primary-supplement-pilot-contract.json).
The [machine-readable review](validation-beneish-supplement-review-2026-10-23.json)
contains all **30 concept-year cells**, their evidence locations and reasons.
Source facts, executable mappings, historical availability and model readiness
remain separate. The frozen `beneish_2013_cashflow_annual_raw_v1` and annual
adapter are unchanged; the paper-target version remains a technical draft.

The closed AV audits still have no usable direct pure-depreciation or noncurrent
debt values, including the recovered increment. A direct IB18/IBEI field is not
established by the [official field documentation](https://documentation.alphavantage.co/FundamentalDataDocs/gaap_documentation.html).
Documented schema presence does not prove actual coverage. Provider cause or
entitlement remains unknown; there is no verified endpoint/upgrade that fills
all three gaps. This is an observed source limitation, not proof that AV could
never supply them. The prepared provider clarification has not been sent.

## Company × year × concept matrix

“Candidate” means the report supports a useful scoped source fact, with no
canonical mapping accepted. “Partial” means useful facts exist but a target
component or income/CFO bridge remains unresolved. These are research judgments,
not the engineering package's value-status labels.

| Company / FY | Pure tangible depreciation | Paper DP14−AM65 | Noncurrent debt / finance leases | IB18 / CFO bridge | Current net trade AR |
| --- | --- | --- | --- | --- | --- |
| AAPL 2024 | Scope ambiguous | Complete components not located | Candidate: separate components | Partial | Candidate |
| AAPL 2025 | Scope ambiguous | Complete components not located | Candidate: separate components | Partial | Candidate |
| MSFT 2024 | Scope ambiguous | Partial components | Candidate: separate components | Partial | Candidate |
| MSFT 2025 | Scope ambiguous | Partial components | Candidate: separate components | Partial | Candidate |
| IBM 2024 | Scope ambiguous | Partial components | Candidate: leases already included | Partial; explicit continuing income | Candidate |
| IBM 2025 | Scope ambiguous | Partial components | Candidate: leases already included | Partial; explicit continuing income | Candidate |

The 30 cells comprise 12 source-mapping candidates, six scope ambiguities,
six partial income/CFO bridges, four partial expense constructions and two
unlocated complete expense component pairs. Accepted executable mappings: **0**.

### AAPL

The reviewed [FY2025 report PDF](https://s2.q4cdn.com/470004039/files/doc_financials/2025/ar/_10-K-2025-As-Filed.pdf)
reports both years. Physical PDF pages 34, 45 and 47 distinguish noncurrent term
debt from current maturities and separate finance-lease liabilities. Pages 34,
37 and 42 distinguish current customer receivables from vendor nontrade amounts.
These facts support debt/lease and trade-AR mapping candidates.

PPE includes internal-use software and finance-lease assets; the reported expense
does not isolate the strict tangible-only target. The coarse billion-unit expense
must retain its display precision. NI and CFO are clear annual consolidated facts,
but the complete historical IB18 exclusions/dividend bridge is not established.
No complete same-scope DP14/AM65 pair was located in this single report.

The document's identity was inspected, but the exact Apple IR-to-PDF link chain
is **not verified**. Both AV and Yahoo use September 30 source labels that differ
from the actual fiscal ends: FY2024 ends September 28; FY2025 ends September 27. Same calendar year is
not an accepted provider-date bridge.

### MSFT

The [official FY2025 annual report](https://www.microsoft.com/investor/reports/ar25/index.html)
contains both selected years. Notes 10 and 13 support separately classified
noncurrent debt and finance leases; current lease amounts already enter current
liabilities. The balance sheet and Note 1 support current net customer AR, distinct
from financing, other and long-term receivables.

Notes 1, 6 and 13 show software and finance-lease assets within PPE. Reported PPE
depreciation is a useful source fact, but no tangible-only decomposition is
established. Note 9 provides intangible amortization; the CF adjustment contains
an additional other component and cannot stand in for historical income-statement
DP14. After-tax NI, common-shareholder attribution and annual CFO are identifiable;
the full historical IB18 and CFO construction remains unresolved. Fourteen
statement/note arithmetic diagnostics passed, without creating a matching tolerance.

### IBM

The [official FY2025 annual report](https://www.ibm.com/downloads/documents/us-en/15db52348fc203a4)
is linked from [IBM financial reporting](https://www.ibm.com/investor/financial-reporting).
Printed pages 44 and 84 show that the **issuer balance-sheet long-term debt already
includes noncurrent finance leases**. Adding the lease liability again would
double count it. This source scope is not automatically assigned to Yahoo's
similarly named field. Current trade notes/accounts receivable are net of
allowances and separate from financing and other receivables.

The CF depreciation adjustment includes operating-lease ROU amortization
(printed p.45). Its coarse billion-unit footnote cannot be subtracted to fabricate
an exact pure-depreciation expense. Separate software/intangible amortization and
segment disclosures provide partial expense evidence, without proving the full
historical DP14/AM65 construction.

Printed pages 42 and 48 explicitly distinguish after-tax continuing income from
nonzero discontinued income and describe NCI attribution. NI is therefore not an
automatic replacement for continuing income. NCI must not be deducted a second
time. Those reported facts are useful;
the complete historical IB18 exclusions/dividend treatment and its relation to
total CFO still require a defined method bridge. No CFO adjustment is invented.

## Native fields are a different denominator

The contract has **59 provider-and-statement-scoped fields: 16 AV + 43 Yahoo**.
Across six selected periods this produces **354 native cells**, separate from
the 30 accounting-review cells. The producer's value-status totals are 166 finite
(48 AV + 118 Yahoo), 94 absent, 78 unavailable and 16 literal missing. These counts
do not establish accounting equivalence or model coverage.

An independent Yahoo review uses explicit field existence and exact-end-date
dimensions: **118 finite + 94 library-field-absent + 46 field-present but no exact
end cell = 258 slots**. Each MSFT year has 25 finite/18 absent; each IBM year has
34/9. Each AAPL year has 20 fields absent and 23 present without an exact target
end. Same-source-calendar-year diagnostics find 20 finite and three typed-missing
Apple cells per year, all retained as unmatched. The income-statement depreciation
candidate is absent for all three companies.

When no exact-end observation exists, a never-observed field is classified as
absent; an observed field without an exact-end cell is unavailable. Thus 78
unavailable cells are not all date mismatches: Apple has 86 unmatched Yahoo slots
comprising 40 absent and 46 unavailable. The 32 unavailable AV slots are also
Apple: 16 fields × two years have September 30 labels rather than the actual
fiscal ends. This is a date gap, not evidence that all those source fields are
absent or missing. No AV or Yahoo Apple date bridge is accepted. The separate 1,540 unmatched records mix
168 AV annual-report rows and 1,372 Yahoo metric-period records; they are **not 1,540 distinct
fiscal periods or years** and carry no target-period assignment.

## Executed scope and limits

Engineering was the sole collector: zero new AV requests; nine Yahoo getters with
11 HTTP dispatches including authentication; three original-document dispatches;
zero retries or redirects. No authorized SEC contact User-Agent was configured,
so SEC document dispatches were zero. No contact identity was invented. Research
made no capture requests and reviewed closed, precisely pinned copies offline.

Original document bytes and Yahoo receipt/table chains passed independent
mechanical intake. The combined selected-slice package is a candidate dataset,
not a replacement for full source-root backups. Source observations and AV inputs
remain preserved separately.

Independent read-only intake verified 100 files, 32 snapshots/datasets, 61 tables
and 8,671 stored rows. The 354/30/1,540 table partitions were independently
recomputed against the fixed native inputs and contract. Code, policy, parent
manifest and copied-byte bindings passed; root files and external dependencies
retained their hashes and modification times. Network, credential, writer,
latest and catalog-discovery attempts were zero. No producer normalizer or
candidate-builder was rerun. This verifies the closed candidate evidence, not
semantic acceptance.

These company documents give coherent FY2025 comparative presentations, not
independently captured FY2024 vintages. Exact SEC accession/IBM EX-13 content
binding and historical availability remain unverified. Provider flow starts,
currency, unit/scale, issuer and accounting scope still need per-fact acceptance;
an exact period-end match does not certify those dimensions. Apple also retains
its authority-link and provider-date gaps. No rounding acceptance tolerance,
missing-to-zero fill, depreciation subtraction or lease addition is authorized.

## Next technical steps

1. Turn the source-supported debt/lease and current net trade-AR candidates into
   explicit source-bound mappings, preserving IBM's inclusive lease scope and
   the separate-component presentation at AAPL/MSFT. Verify each provider field
   against the actual issuer fact before assigning it that scope.
2. Finish the IB18 inclusion/attribution/dividend and CFO construction from the
   evidence, with missing adjustments left unresolved. Keep continuing income,
   reported NI and CFO separate throughout.
3. Resolve the strict tangible-only policy versus historical DP14−AM65 target in
   a separately reviewed method/input version. Where decomposition remains
   unavailable, keep the strict method unavailable; do not relabel a CF aggregate.
4. Close authority, exact source-version and provider date/context gaps before
   accepting executable inputs. Historical-availability work is a separate gate
   before any backtest. Expanding collection or adding a paid source is outside
   this completed pilot.

Keep original disclosures as the key-gap supplement and Yahoo as a candidate
layer. If an essential construction stays unresolved, retain that method's
unavailable status. WRDS/Compustat live access is excluded; FMP remains a future
conditional option without a purchase, request or claim of sufficient coverage.

## Full declared Drive bundle: independent receipt review

The full original and currency-derived closures have now completed the recorded
real Drive upload, authenticated byte download and same-Mac OS-isolated recovery.
This supersedes the earlier pending full-bundle state; the 397-snapshot sample
remains a separate historical test. The encrypted archive is **63,129,600 bytes**.

| Declared version | Data files | Selected financial tables | Financial rows |
| --- | ---: | ---: | ---: |
| Original baseline | 4,322 | 2,788 | 133,180 |
| Currency-derived | 4,762 | 3,006 | 141,303 |

The versions overlap and must not be summed as unique observations. Derived
quarantine and normalization-audit tables are separate diagnostic evidence.
An independent read-only review rehashed 9,361 existing local artifacts and
verified the final transfer/recovery receipt chain, archive members, manifests,
restored payloads, reader-origin bindings and recorded OS controls. No new
download, decryption, reader or restic execution was performed by that review.
Recorded owner-only metadata was checked; current cloud permissions were not
requeried. Existing failed attempts and the successful continuation are retained.

This certifies the recorded full-bundle/current-Mac milestone, not complete
disaster recovery. Another physical machine, a clean runtime/offline dependency
rebuild and off-machine key retrieval remain untested. Eight historical failed
provider-response bodies remain unavailable. The full bundle does not automatically
cover later supplement-pilot captures or every SRG asset, and recovery does not
qualify accounting semantics or historical investment use.

Related work: [PR #19, merged](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/19),
[source-options review #20](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/20),
[audit-only recovery and frozen pilot #21](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/21),
and [engineering candidate package #22](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/22).
The latter remains a draft dependency, not a research acceptance or merge.
