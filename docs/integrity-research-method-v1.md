# Integrity research method v1

Status: research definitions and acceptance criteria; implementation and current
source-acceptance limits are documented in the [annual calculator](annual-beneish-calculator.md).
Prepared 2026-10-22 (America/Toronto). The companion
[machine-readable contract](integrity-research-contract-v1.json) identifies the
selected definitions. The method contract itself does not certify a provider,
fraud classifier, Integrity composite or market result.

## Scope and order

Integrity is the research programme's name, not a measured latent property or an
existing validated score. Keep three outputs separate:

| Priority | Output | Meaning and direction | Initial use |
| --- | --- | --- | --- |
| 1 | `beneish_2013_cashflow_annual_raw_v1` | Eight-ratio linear M-score; higher M is the risk direction | Annual statement diagnostic after the strict field contract passes |
| 2 | `accrual_quality_ttm_avg_assets_v1` | Negative cash-flow accrual intensity; higher means lower accrual intensity | Independent quality comparator, not another Beneish component |
| 3 | `benford_statement_diagnostics_v1` | First/second-digit discrepancies and sample coverage | Descriptive data diagnostic only |

Do not average these outputs or select their weights from subsequent returns.
Unknown Adjusted M1/M2, the old fixed-five recipe and full-panel normalization
remain historical references. They do not define this version or block its work.
TTM Beneish is a later, separately versioned extension; consecutive individual
quarters are not a substitute for two annual observations.

Collect the full frozen current S&P 500 universe. Research eligibility is a
separate company-level decision: the primary Beneish cohort excludes financial
services businesses; use SIC 6000–6899 when a verified SIC is supplied. A different
taxonomy needs an explicit reviewed mapping, including REIT treatment, before
eligibility is assigned. Unknown classification stays unverified. Retain excluded
companies in the coverage report. Multiple share classes share one issuer-level
financial score; keep their dated security links separate. Current constituents
support current-snapshot description, not historical index membership.

## Beneish definition

Use the **2013 cash-flow construction with raw ratios**, not a claim to reproduce
the complete 1999 model estimation or 2013 return study. Here `t` is the current
fiscal year and `p` the immediately preceding fiscal year of the same issuer.
Stocks are measured at each year end; flows cover that corresponding full year.
All amounts use one documented currency, scale and compatible reporting scope.

| Ratio | Exact formula | What it describes |
| --- | --- | --- |
| DSRI | `(AR_t / Sales_t) / (AR_p / Sales_p)` | Change in receivables relative to sales |
| GMI | `((Sales_p - COGS_p) / Sales_p) / ((Sales_t - COGS_t) / Sales_t)` | Prior/current gross margin |
| AQI | `(1 - (CA_t + PPE_t) / TA_t) / (1 - (CA_p + PPE_p) / TA_p)` | Change in residual asset share |
| SGI | `Sales_t / Sales_p` | Sales growth |
| DEPI | `(Dep_p / (Dep_p + PPE_p)) / (Dep_t / (Dep_t + PPE_t))` | Prior/current depreciation rate |
| SGAI | `(SGA_t / Sales_t) / (SGA_p / Sales_p)` | Change in SG&A intensity |
| TATA | `(IBEI_t - CFO_t) / TA_t` | Current cash-flow accruals / ending assets |
| LVGI | `((CL_t + LTD_t) / TA_t) / ((CL_p + LTD_p) / TA_p)` | Change in liabilities/debt intensity |

```text
M = -4.840 + 0.920*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI
           + 0.115*DEPI - 0.172*SGAI + 4.679*TATA - 0.327*LVGI
```

The formula and cash-flow choice follow [Beneish, Lee and Nichols (2013),
Appendix A, p.76 and p.60](https://cpb-us-w2.wpmucdn.com/sites.udel.edu/dist/a/855/files/2020/07/Earnings-Manipulation-and-Expected-Returns.pdf#page=20).
Two source issues are resolved explicitly: Appendix B p.78 describes average
assets for accruals, whereas Appendix A uses ending assets. This version chooses
ending assets, also supported by the author's Sunbeam example. Exhibit A1 repeats
a Compustat item number for COGS and net PPE; map semantic concepts, not that
ambiguous printed code. The paper's annual 1%/99% winsorization is not applied to
this raw diagnostic; a later transformed study requires its own definition.

The continuous M-score is primary. An optional reference screen is **M > -1.78**,
with equality unflagged. This is the historical unweighted-model cutoff, not a
calibrated decision rule for today's S&P 500. No sigmoid, fraud probability or
accusation is returned. The legacy -2.22 rule is not adopted. Neither the negative
SGAI/LVGI coefficients nor any component should be sign-flipped to make all terms
look like standalone risk indicators. See the [author's Sunbeam example,
p.3](https://apps.kelley.iu.edu/Beneish/Content/Examples/SunbeamExample.pdf#page=3).

## Required financial fields and candidate Alpha Vantage mapping

These are **12 concepts**, six stocks and six flows. The eight formulas need the
first ten fields in both years plus current IBEI/CFO: 22 amounts. The author's
[calculator](https://apps.kelley.iu.edu/beneish/mscore/mscoreinput) accepts 24
amounts; prior IBEI/CFO can be retained for reconciliation but are not used in M.

AV mappings below are a requested adapter contract, not certified source data.
The [official US GAAP field dictionary](https://documentation.alphavantage.co/FundamentalDataDocs/gaap_documentation.html)
supplies candidates. Verify actual payload values and issuer reporting scope
before assigning `verified_exact`; non-US-GAAP inputs require their own mapping.

| Concept / canonical name | Basis | AV candidate | Required semantic check |
| --- | --- | --- | --- |
| AR / `trade_receivables_net` | Year-end stock | BS `currentNetReceivables` | Broad current receivables can include nontrade balances; proxy until equivalence is evidenced |
| CA / `current_assets` | Year-end stock | BS `totalCurrentAssets` | Complete current assets |
| CL / `current_liabilities` | Year-end stock | BS `totalCurrentLiabilities` | All current liabilities, not current debt alone |
| TA / `total_assets` | Year-end stock | BS `totalAssets` | Total assets on the same consolidation basis |
| PPE / `net_ppe` | Year-end stock | BS `propertyPlantEquipment` | Net carrying amount, not gross PPE |
| LTD / `long_term_debt_noncurrent` | Year-end stock | BS `longTermDebtNoncurrent` | Excludes current maturities already in CL; never silently use total debt |
| Sales / `sales` | Annual flow | IS `totalRevenue` | Compatible net sales/revenue scope |
| COGS / `cost_of_goods_sold` | Annual flow | IS `costofGoodsAndServicesSold` | Compatible direct cost; `costOfRevenue` is a separate candidate needing evidence |
| Dep / `depreciation` | Annual flow | IS `depreciation` | Tangible-asset depreciation only; D&A/DD&A is not an automatic substitute |
| SGA / `sga_expense` | Annual flow | IS `sellingGeneralAndAdministrative` | SG&A only; not all operating expenses |
| IBEI / `income_before_extraordinary_items` | Current annual flow | No direct certified mapping; inspect `netIncome` and `netIncomeFromContinuingOperations` | Extraordinary/discontinued items and parent/consolidated scope need a bridge; neither candidate is equivalent by name |
| CFO / `operating_cash_flow` | Current annual flow | CF `operatingCashflow` | Same annual window and compatible entity/income scope |

The table requests fields even when current payloads omit or null them. A field
listed in documentation is not evidence of actual coverage. Missing depreciation,
noncurrent debt or an IBEI bridge blocks a strict score. Any permitted future proxy
must have another definition ID, enumerate substitutions and retain
`standard_definition_satisfied=false`; do not backfill the standard result.

An [aggregate check of the existing fresh three-issuer trial](validation-av-beneish-field-readiness-2026-10-22.json)
found zero finite `depreciation` and `longTermDebtNoncurrent` values among each
endpoint's 60 annual / 243 quarterly rows. This does not generalize to the full
universe, but it establishes that the trial is not strict-model ready. Nine raw
snapshot hashes match their collection receipts. This bounded field inspection
calculates no factor and is not provider integration; raw amounts remain private.

## Observation contract and rejection policy

One selected observation per issuer / fiscal period / concept / source version.
Retain `entity_id`, provider symbol and dated security links; `period_start`,
`period_end`, `fiscal_year`, `period_type`, `flow_basis`; `currency`, `unit_scale`,
sign convention and consolidation/accounting scope; source field and mapping
evidence; provider/request, `snapshot_id`, normalizer/table and raw hash;
`observed_at`, actual publication/version-availability timestamps when known,
and universe/classification version. Preserve source missingness.

Strict annual acceptance requires:

- The same issuer and adjacent verified fiscal years. Each actual annual window
  and the year-end spacing must be 330–400 days; this is an SRG guard, not an
  inferred fiscal calendar. Fiscal-year changes, stubs, overlaps and unknown
  starts are rejected from the strict cohort or separately reviewed/versioned.
  A provider-labelled annual record with unknown duration may support a labelled
  arithmetic candidate only; it does not satisfy this contract.
- Same currency, explicit scale and compatible scope across the entire pair.
  Any conversion is recorded with its evidence; never simply relabel metadata.
  Expense values use a documented positive-cost convention, without `abs()`.
- `verified_exact` semantics for every required field and all finite amounts.
  For the primary cohort follow the calculator's positive-input domain: AR, CA,
  CL, TA, PPE, Sales, Dep, COGS and SGA must be >0 in both years; LTD >=0.
  IBEI/CFO may be negative. This conservative domain can exclude mathematically
  computable cases and is reported as a research policy.
- Every actual intermediate denominator is nonzero and finite. In particular,
  nonpositive gross margin in either year or nonpositive residual asset shares are
  out-of-domain in this primary specification, even if division is possible.
  No epsilon replacement, neutral-ratio filling, clipping or winsorization.
- Unique selected versions. Resolve source conflicts explicitly; row order,
  averaging duplicate filings or combining mismatched annual windows is invalid.
  Empty/missing/invalid outputs are null with reason codes, never zero or a
  reassuring flag. An arithmetic result alone cannot set source/timing status.

## Independent accrual-quality comparator

```text
Q_t = -(sum(NI_q, q=t-3..t) - sum(CFO_q, q=t-3..t))
      / ((TA_(t-4) + TA_t) / 2)
```

Use four consecutive verified quarterly net-income and operating-cash-flow
amounts, plus beginning/ending assets (five quarter-end observations). Here NI
is the explicitly documented net-income concept selected for this separate
study; it is not silently relabelled IBEI. Positive beginning and ending assets,
common currency/scale/scope and complete windows are required. Actual quarterly
windows must be consecutive and nonoverlapping; 60–120-day adjacent-end and
330–400-day full-year screens are mechanical checks, not proof of flow basis.

AV `quarterlyReports` are candidate quarterly flows, not automatically YTD.
YTD differencing is used only for sources verified as YTD, within fiscal years.
Do not mix quarterly and YTD paths or fill missing quarters from annual amounts.
This definition uses average assets and differs deliberately from Beneish TATA's
ending-assets denominator. Reuse the existing
[accrual protocol](financial-quality-study.md), with this source-specific flow
check; no composite or new return experiment starts here.

## Benford diagnostic boundary

Use the existing [significant-digit contract](benford-diagnostics.md).
`P(D1=d)=log10(1+1/d)`; second-digit probabilities are its 90-bin marginal.
For each frozen set of eligible monetary observations report valid/zero/invalid
counts and `sum((count - n*p)^2/(n*p))`. Selection, duplicate totals, rounding,
amount dependence and magnitude restrictions must be disclosed. Counts/coverage
always accompany discrepancies. The cell-count screen is not proof that a
statement's fields form an independent Benford sample. No p-value, fraud label,
ranking input or Integrity-composite weight is authorized in v1.

## Acceptance gates

These are requirements for later implementation and data acceptance, not claims
that the current pipeline passes them.

| Gate | Evidence required | Allowed conclusion |
| --- | --- | --- |
| A. Definition | Formula/version, field dictionary, direction, domain, null policy and sources fixed | Method contract ready for implementation |
| B. Arithmetic | Independently derive all eight Sunbeam ratios from published amounts; match displayed ratios within 0.00005 and M within 0.0005; unrounded score agrees with existing coefficient function within 1e-12 | Formula arithmetic verified on a public fixture |
| C. Adapter/source | Exact snapshot replay; per-field mapping/units/scope/duration evidence; rejection cases; no mutation/network; full frozen-universe success/excluded/failed/unverified accounting | Strict or explicitly proxy snapshot diagnostics for the reported eligible subset |
| D. Historical availability | Authentic input vintages and effective-dated identity/membership; all selected input versions public by decision time; explicit processing delay and next execution; future-mutation and revision-boundary tests | Eligible for a separately preregistered historical study |
| E. Empirical validity | Separate protocols for classification and return prediction, untouched temporal holdout, uncertainty and negative results | Only the specific supported claim |

Adapter tests at gate C must cover missing/NaN/Inf/booleans, zero/negative domain,
zero intermediates, mixed units/currency/issuer, fiscal gaps/stubs, ambiguous
versions and proxy substitutions. Test common-scale invariance, permutation
invariance after key selection, input immutability, and independent hand
calculations. Report counts and denominator definitions for all universe members;
100% API responses is not required score coverage, and no arbitrary coverage
percentage may override a failed semantic gate.

For gate D, `observed_at` proves capture time only. A current revised historical
amount cannot inherit the original release date. `reportedDate` from EARNINGS
cannot authenticate all statement versions. Missing timing permits snapshot
description only. OfflineDataReader date filtering is not historical as-of
selection. Preserve source/timing/definition/arithmetic statuses separately.

Before gate E, fraud validation needs independently defined, timestamped and
mature labels, issuer-level temporal splits, base rates, precision/recall,
PR-AUC and uncertainty; a high M-score cannot supply its own ground truth.
Probability claims additionally require held-out calibration. Return validation
needs a preregistered primary hypothesis (lower M / higher Q predicts higher
next-month returns), calendar boundaries, controls, executable returns/costs and
multiple-test policy. Freeze those choices before seeing outcomes; use the
existing monthly study protocol as a starting point. Presenting positive IC alone
does not satisfy either fraud validation or tradable-alpha validation.

## Reproducible method check and implementation handoff

```bash
python examples/verify_integrity_method_contract.py
pytest -q tests/test_beneish_mscore.py tests/test_benford.py tests/test_financial_quality.py
```

The public check recomputes an author-supplied fixture with Decimal arithmetic,
compares the existing coefficient function and checks common-scale invariance.
It does not read provider data, validate an adapter or clear gates C–E. Its saved
[verification receipt](validation-integrity-method-v1.json) records the actual
checked scope. Public fixtures are not statistical samples.

Engineering owns raw snapshots, identity/universe metadata, normalization and
versioned reads. Research owns concept mappings, period eligibility, formulas
and these acceptance gates. The [annual calculator and pinned source review](annual-beneish-calculator.md)
implement public/synthetic checks and source-gap reporting; acceptance of real
inputs through gate C remains separate.
If AV-only data cannot satisfy a field, report the gap or define a separately
named proxy; no new source or hidden substitution is implied.
