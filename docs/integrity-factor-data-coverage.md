# Integrity Factor: definitions and input coverage

This is a source and schema map for rebuilding the earlier Integrity Factor.
It is not a replacement research specification, a live progress checkpoint, or
an investment result. The current project progress Page remains the status
authority. The code review baseline for this map is `d523a93695e1af3f5136b29f067b170a115c7461`.

## What can be traced in this checkout

The user-defined scope includes Benford, Beneish and earnings/accrual quality.
Only some of that scope has an identifiable implementation here. The
[legacy migration inventory](legacy-migration.md) describes Python-module
consolidation; it explicitly excludes legacy notebooks and their outputs.
The [private-source manifest](financial-quality-source-manifest.json) preserves
hashes and neutral roles for seven notebooks. It does not contain their code.
Neither inventory establishes that the entire original Integrity Factor was
migrated or that its historical results were reproduced.

| Component | Definition traceable here | Implementation and boundary | Required next verification |
| --- | --- | --- | --- |
| Benford first/second significant digit | Descriptive count discrepancies against the expected digit distributions; see [mathematical and timing contracts](benford-diagnostics.md) | [`benford_snapshot_diagnostics` and `benford_asof_diagnostics`](../src/systematic_alpha_lab/factor_research/factors/benford.py). Arithmetic and supplied-timestamp selection have tests. Legacy automatic daily projection raises a migration error. | Select and justify financial amount fields, preserve units/coverage, then recompute snapshot diagnostics. Genuine field-version publication times are required before historical signal formation. A discrepancy is not a fraud probability. |
| Beneish | Original Q07 quarterly proxy recovered; eight-ratio coefficients independently checked | [`beneish_m_score` and `legacy_q07_quarterly_proxy`](../src/systematic_alpha_lab/factor_research/beneish.py) preserve explicit ratio arithmetic and the legacy quarterly definition, with missing/finite/entity/period guards. This is not the published annual model. | See [definition reconciliation](integrity-definition-reconciliation.md). Adjusted M remains unresolved; a standard annual/TTM variant and its provider field mapping still need separate validation. |
| Legacy annual accruals | `(annual netIncome - annual operatingCashflow) / annual totalAssets` | [`Accruals`](../src/systematic_alpha_lab/factor_research/factors/accruals.py) uses annual provider fields, averages duplicate company/period rows, optionally forward-fills on price dates, then shifts one row. This is outside the verified TTM slice. | Review duplicate/version handling, positive-asset checks and release timing before reuse. Do not interpret fiscal-period indexing or a one-row shift as publication evidence. |
| Negative TTM accrual intensity | `-(sum(last four quarterly NI) - sum(last four quarterly CFO)) / ((assets[t-4] + assets[t]) / 2)` | [`quarterly_accrual_diagnostic` and `accrual_from_quarterly_flows`](../src/systematic_alpha_lab/factor_research/financial_quality.py); [locked protocol](financial-quality-study.md). YTD cash-flow conversion and already-quarterly flows are separate input contracts. | Recompute from explicit source snapshots and verify dependencies, currency, units, quarter continuity and opening assets. Arithmetic readiness alone does not clear the historical research gate. |
| Broader earnings quality / combined Integrity score | A located report version states five signed terms with coefficient magnitude 0.2 and selects Adjusted M1; its input transformations and lineage remain unresolved | The [definition-gap audit](integrity-definition-gaps-2026-10-22.md) distinguishes the written five-factor recipe from the same report's broader appendix and saved sixteen-factor output. Earlier whole-panel scaling/PCA and return-based weight selection do not supply an accepted historical signal. | Recover the Adjusted M1 generator and an operational contract connecting exact inputs to the fixed recipe. Keep the narrow TTM study separate from the wider restoration. |

The configured `theta_info_forensic_drift` and `theta_pure_quality` in
[`config/factors/config.json`](../config/factors/config.json) are other named
composites. Their component lists are not evidence for the original Integrity
Factor definition. In particular, neither contains a Beneish component. The
existing Piotroski implementation is also not automatically added to this task.

## Monetary fields and adapter coverage

These are field contracts, not a claim that every required field is populated.
Provider financial fields retain their original strings in
[`normalize_reports`](../src/systematic_alpha_lab/data_pipeline/fundamental_snapshots.py);
the normalizer does not verify units, flow basis, original vintages or publication
times. The [provider annual](provider-statement-review.md),
[provider quarterly](provider-quarterly-review.md) and
[SEC quarterly](sec-quarterly-review.md) adapters retain different source
assumptions. They must not be mixed silently.

| Use | Required monetary fields | Available/derivable route | Missing or unresolved contract |
| --- | --- | --- | --- |
| Existing Benford legacy snapshot adapter | Income: `totalRevenue`, `grossProfit`, `operatingIncome`, `netIncome`, `sellingGeneralAndAdministrative`; balance: `totalAssets`, `totalCurrentAssets`, `totalCurrentLiabilities`, `inventory`, `propertyPlantEquipment` | `_prepare_long` selects these fields when present in explicit quarterly statement tables. The general diagnostic accepts an explicitly selected long-form field/value table. | This field list is the current adapter's selection, not a certified original Integrity specification or a proof of suitability for Benford. Missing fields must be visible; monetary basis and dependence among related totals need review. Do not auto-select identifiers or fiscal labels as amounts. |
| Legacy annual accruals | Annual `netIncome`, `operatingCashflow`, `totalAssets` | Provider annual statement tables; no new download is inherent in the calculation. | A current asset denominator differs from the average-assets denominator below. Do not treat their outputs as the same signal. |
| TTM calculation from already-quarterly flows | `net_income`, `operating_cash_flow_quarter`, `total_assets` | Four quarterly flows plus opening/closing assets over five consecutive observations. [`accrual_from_quarterly_flows`](../src/systematic_alpha_lab/factor_research/financial_quality.py) enforces amount, spacing and basis checks. | Provider flow/scale declarations remain assumptions until verified. Missing quarters are not created from annual totals. |
| TTM calculation from YTD cash flow | Quarterly `net_income`, `operating_cash_flow_ytd`, `total_assets`, fiscal year/quarter | [`quarterly_accrual_diagnostic`](../src/systematic_alpha_lab/factor_research/financial_quality.py) resets Q1 and differences adjacent YTD observations within the same fiscal year. The SEC adapter can also retain explicit reported-quarter and YTD-difference contexts and filing dependencies. | Prior YTD observations, authentic contexts and original versions must be available. Cross-year `diff()` and arbitrary adjacent filings are not accepted replacements. |
| Beneish | Legacy quarterly proxy requires receivables, sales, COGS, current assets, net PPE, total assets, depreciation, SG&A, long-term debt and current liabilities for one explicit consecutive company-quarter pair | The recovered CSV adapter maps the original ten fields without changing their basis; a public synthetic pair verifies the calculation. No standard annual/TTM provider adapter is implied. | Currency/unit/source vintage and the original quarterly proxy's model suitability remain unverified. Published 1999 and 2013 accrual definitions differ from this proxy. A similarly named provider field does not establish accounting equivalence. |

## Coverage of the recovered input types

The following describes the restored package schemas reviewed for this map;
private values, raw responses, accessions and local paths are not distributed in
this document. It is not a complete inventory of all data the user may own.

- The recovered market package contains monthly price tables. Price fields do
  not provide the statement amounts required by Benford or accruals.
- The recovered SEC package contains normalized facts/filings and derived
  quarterly reviews. The combined review schema exposes net income, operating
  cash flow and assets, their source text, contexts/dependencies and readiness
  flags. This can support the defined accrual arithmetic; it is not the broader
  ten-field Benford input panel or a validated Beneish input panel.
- More raw SEC concepts may be present in the facts table. Presence alone does
  not settle concept mapping, period/stock-versus-flow semantics, units,
  contexts, missingness or version selection for another component.
- No normalized Alpha Vantage annual/quarterly statement tables were found in
  these two restored packages. The provider collection/replay/review code exists,
  but that is different from having its real financial captures restored here.
  A separately preserved provider capture may be registered later, or refreshed
  through an explicitly authorized collection step. No credential read or
  automatic provider request is implied by this map.

## Evidence returned to downstream research

For each explicit source request, retain snapshot identity and digest, normalizer
version, source observation time, period/date coverage, selected and missing
fields, and any available calculation/timing/unit/identifier status. Observation
time is the capture time; it is never substituted for historical public
availability. Provider symbols and SEC company identifiers do not by themselves
identify the historical traded security.

An offline reader may return incomplete data for inspection with those gaps
visible. It must not promote source coverage or a nonmissing diagnostic to
historical admissibility. Before any return join, apply the
[financial-quality data gate](financial-quality-study.md): authentic publication
and version evidence for all dependencies, effective-dated security links,
historical membership including exits, total/delisting returns, dated controls
and an execution calendar. No fixed lag, current constituent list or guessed
ticker mapping fills these requirements.

## Recalculation order

1. Verify exact source captures and expose coverage/missingness through the
   shared offline reader; preserve each source's accounting/timing assumptions.
2. Recompute the traceable accrual arithmetic and source reconciliation from the
   same selected versions, comparing exact inputs and defined tolerances.
3. Assemble the explicitly selected Benford amount panel, record exclusions and
   sample-size screens, and recompute descriptive diagnostics.
4. Recover the missing original Beneish and combined-score specification, then
   add field mappings and independently verified arithmetic. Do not invent a
   replacement merely to complete the table.
5. Reconcile old/new values only where definitions and source versions are
   comparable. Label differences caused by definitions, source revisions,
   missingness, arithmetic corrections or unresolved evidence separately.

These steps can progress without a market-return study. Component restoration,
source readiness and evidence for investment performance are separate outcomes.
