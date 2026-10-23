# Beneish source targets, alternatives and recovery acceptance

Prepared 2026-10-23 (America/Toronto). [PR #19](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/19)
was independently reviewed and merged after 799 local tests, 42 focused audit
tests, lint/diff checks and Python 3.10/3.11 CI passed at its exact head.
The [aggregate receipt](validation-source-options-and-drive-recovery-2026-10-23.json)
separates that code validation, source research and the bounded recovery trial.

**Decision status:** the audited Alpha Vantage (AV) collection cannot currently
satisfy the frozen strict v1 inputs. Public documentation does not demonstrate
another AV endpoint or product that fills all three gaps. This is not proof that
AV can never supply them. A more fundamental target-definition discrepancy also
needs resolving before choosing a supplement. No calculator, contract, provider
or research eligibility rule is changed by this note.

**Subsequent direction update (2026-10-23):** retain AV as the primary source and
assess supplemental candidates, including Yahoo Finance via yfinance and original
filings, for at most three issuers across two adjacent annual periods. This bounded
feasibility direction is now selected; no supplemental field is thereby accepted
as a standard-model input. The initial note's unselected status remains part of
the decision history. Research owns target/mapping review; shared-data engineering
is the sole collector. No new source values are captured by this document change.

**Current source policy:** qualified, nonmissing AV is primary. SEC/issuer
original disclosures support key gaps and accounting verification; yfinance is
for quick candidates and cross-checks. WRDS/Compustat access is excluded as a
dependency, and FMP remains a future conditional candidate with no paid service
added. [PR #21](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/21)
contains the frozen bounded collection contract and technical method-review draft.

## Reconcile the target before repairing the data

The [2013 paper, Appendix A / Exhibit A1, printed p.76](https://cpb-us-w2.wpmucdn.com/sites.udel.edu/dist/a/855/files/2020/07/Earnings-Manipulation-and-Expected-Returns.pdf#page=20)
uses depreciation `[14-65]`, income before extraordinary items `[18]`, and
leverage `(5+9)/6`. These explicit entries require their own interpretation;
the separate duplicated item number for COGS/PPE does not erase them.

The historical S&P Compustat manual gives the following distinctions:

| Target | Historical vendor meaning | Implication for SRG |
| --- | --- | --- |
| [DP14](https://sites.bu.edu/qm222projectcourse/files/2014/08/compustat_users_guide-2003.pdf#page=265) minus [AM65](https://sites.bu.edu/qm222projectcourse/files/2014/08/compustat_users_guide-2003.pdf#page=200) | Income-statement D&A minus intangible amortization; depletion and some other amortization can remain. Cash-flow D&A is a distinct item. | Not universally pure tangible depreciation; neither AV D&A series is automatically equivalent. |
| [LTD9](https://sites.bu.edu/qm222projectcourse/files/2014/08/compustat_users_guide-2003.pdf#page=352) | Normally excludes current maturities, includes capitalized leases; flagged exceptions require review. | A debt-only noncurrent field or total-minus-current calculation needs a lease/scope bridge. |
| [IB18](https://sites.bu.edu/qm222projectcourse/files/2014/08/compustat_users_guide-2003.pdf#page=314) | After tax/minority interest, before common/preferred dividends; excludes after-tax discontinued operations and extraordinary items, includes special items. | Continuing parent-attributable income is a candidate direction, subject to a compatible CFO bridge. |

These are August 2003 definitions. The frozen
`beneish_2013_cashflow_annual_raw_v1` requests **pure tangible depreciation**, a
narrower SRG policy; historical source-target equivalence is not certified. The
public author example validates arithmetic, not those mappings.

Keep v1 unchanged and blocked. If the intended target is the paper's historical
construction, specify and review a new method version, source bridges and
fixtures first. If the pure-depreciation policy is retained, name its departure
explicitly. Neither path inherits a calibrated contemporary fraud screen or a
validated investment result.

## What AV can establish now

The [official GAAP dictionary](https://documentation.alphavantage.co/FundamentalDataDocs/gaap_documentation.html),
[provider overview](https://documentation.alphavantage.co/FundamentalDataDocs/index.html)
and [endpoint documentation](https://www.alphavantage.co/documentation/) were
reviewed. The existing [closed-collection audit](beneish-source-feasibility.md)
is the observed-value evidence; this follow-up makes no new financial API calls.

| Gap | Evidence from the original closed collection | Remaining requirement |
| --- | --- | --- |
| Pure depreciation / paper expense target | IS `depreciation`: 0 finite / 8,809 annual and 0 / 35,259 quarterly rows. Separate amortization/depletion probes are absent. | AV documents pure depreciation, but usable observations and a complete paper-target decomposition are not demonstrated. |
| Noncurrent debt | BS `longTermDebtNoncurrent`: 0 / 8,892 annual and 0 / 35,592 quarterly. Total-minus-current is negative in 316 / 4,474 annual source rows with both components finite. | Even nonnegative component pairs need compatible composition. AV's documented noncurrent field excludes capital-lease obligations; the paper target needs that bridge. |
| IBEI | Direct IBEI probe absent; continuing-income and net-income names do not certify equivalence. CF `profitLoss` has zero finite rows, so the same-row income comparison has a zero denominator. | Resolve discontinued/extraordinary items, attribution, CFO scope and source versions; missing components are not zero. |

No public evidence reviewed establishes that a subscription upgrade fixes these
issues. The missing-value cause, product-specific availability and a provider
source-tag explanation remain unknown. The bounded questions in the prior audit
are ready for provider clarification; they have **not been sent**. Arithmetic
alone, including IS/CF D&A subtraction, cannot supply missing accounting evidence.

## Three available paths

| Path | Work and tradeoff | Acceptance / decision status |
| --- | --- | --- |
| **1. AV only, retain strict v1** | Keep the shared AV inputs and null outputs; seek documented provider clarification. Least additional engineering, but no demonstrated route or ETA to a valid score. | Available now; blocked inputs remain blocked. No purchase or provider contact has been made. |
| **2. AV plus bounded supplemental-source feasibility — selected direction** | Resolve the expense/debt/income targets through technical review. Check candidate coverage for at most three issuers across two adjacent annual periods, supplementing only genuine gaps after validation. Public SEC access needs no data subscription; extraction and accounting review are the real effort. | Bounded feasibility selected; supplemental values and mappings remain unaccepted. Inspect yfinance candidates and original filings as needed. No automatic market-wide expansion or score calculation. |
| **3. Separately named AV proxy** | Explicitly choose available D&A, debt and income definitions, disclose substitutions and validate a different research output. Easier coverage may trade away the historical target. | Requires a new definition ID and `standard_definition_satisfied=false`. No automatic historical cutoff, fraud-probability or empirical-performance interpretation. Not implemented. |

For path 2, reuse the existing [SEC snapshot connector](sec-filing-snapshots.md)
and `select_sec_context`; do not build another pipeline. The
[SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
limits aggregate XBRL endpoints to noncustom taxonomy facts applying to the whole
entity. Custom tags and note-specific breakdowns can require original filings;
there is no all-company completeness guarantee. Match issuer, accession, tag,
unit, annual start/end, currency/scale, consolidation, lease/income scope and
restatement version. A current filing download alone does not establish historical
availability. Stable issuer links, fiscal/flow metadata, units, classification
and publication timing remain separate gates under every path.

## Keep the new engineering recovery separate

The source rates above cover **1,394 succeeded / 115 failed / 1,509 original
tasks**, for 503 ETF-proxy securities. They are not a field audit of the newly
delivered currency-quarantine recovery version. A read-only aggregate check of
that closed handoff confirms 109 recovered selections with 8,123 retained rows
and 1,204 quarantined rows. Combined three-endpoint coverage reaches 501
securities; 46 have quarantined periods, and two securities' six tasks still lack
usable data. Its [engineering PR #16](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/16)
remains a draft. At initial preparation, research intake was pending. The
subsequent [PR #21](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/21)
records a passed explicit field-audit intake and exhaustive raw/accepted/quarantine
partition for all 109 recovered selections. Annual scoring remains v1-only;
that audit does not accept the materialization for scoring. Restored
coverage does not certify accounting semantics, exact S&P 500 membership or
historical point-in-time use. The original batch and eight unavailable historical
failed-response bodies remain part of the evidence account.

## Drive sample: real download and recovery passed

Independent review followed the actual upload and authenticated download into
an independently restored repository, then checked the restored reader result.
This is a **397-snapshot sample**, with **1,192 data files, 794 financial tables
and 38,105 rows**, not the full original collection or the new recovery version.

- Drive owner-only metadata was checked; downloaded bytes and archive digest
  matched the uploaded 14,837,760-byte archive.
- `restic check --read-data`, pinned-snapshot `restore --verify`, closure/payload
  verification, code-bundle checks and baseline reader comparison passed.
- The OS-isolated reader was denied the old data and reader-source paths and
  tested network and credential access; the reader's Python network blocker
  recorded zero attempts.
- A Python 3.9 failure is retained. The successful run used Python 3.12.14 and
  a prepared environment. Final completion evidence retains earlier events.

The test used another directory on the **same Mac** and reused its prepared
runtime. A different machine, a clean environment rebuild, off-machine key
recovery and the full-batch cloud package are **not yet accepted**. Account-wide
quota was not read; server acceptance establishes capacity for this sample only.
No paid configuration was performed. Full-bundle recovery must preserve raw,
catalog, normalized objects, batch/universe/identity/lineage evidence, code,
environment and external dependencies, and declare the historical body gaps.

## Validation boundary

This change contains documentation and a manually sanitized aggregate receipt.
It neither reruns the source audit against the new engineering version nor
calculates Beneish scores. Public records contain no private source identifiers,
observed timestamps, source fingerprints, raw financial values, private paths,
cloud object identifiers or credentials. Public aggregate evidence supports the
stated scope; authenticating private source and restore lineage still requires
authorized private records. Live status remains on the existing SRG main progress
Page; this dated note is evidence, not another checkpoint.
