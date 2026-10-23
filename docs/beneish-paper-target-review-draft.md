# Draft review: annual Beneish source targets

Prepared 2026-10-23. **Technical proposal; no calculator or method change.**
Proposed review label: `beneish_2013_paper_target_annual_raw_v2_draft`.
This label is not registered as an executable or accepted definition.
The source direction is AV primary, with SEC/issuer original disclosures preferred
for key gaps and concept verification. yfinance supplies quick candidates and a
bounded cross-check. WRDS/Compustat access is not a dependency; its historical
manual remains reference material. FMP is a future conditional option, with no
purchase or collection selected. Actual supplementary values and mappings have
not been accepted. The [pilot collection contract](av-primary-supplement-pilot-contract.json)
limits engineering to AAPL, MSFT and IBM, FY2024/FY2025, with exact issuer calendars
and independent fact-context checks.

[PR #20](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/20) records the
source-options evidence and its historical decision state. This proposal follows
the later supplementary-source direction; it does not reopen an AV-only choice.
Accounting target reconciliation is research work to resolve from evidence.

## Separate the frozen policy from the paper target

Keep `beneish_2013_cashflow_annual_raw_v1` unchanged. Its pure tangible depreciation
requirement is SRG's narrower policy; an author arithmetic fixture does not certify
provider concepts. The new `av_fundamentals_currency_quarantine_v1` intake is
**field-audit only**. The annual scoring adapter remains v1-only.

The [2013 Appendix A, printed p.76 / PDF p.20](https://cpb-us-w2.wpmucdn.com/sites.udel.edu/dist/a/855/files/2020/07/Earnings-Manipulation-and-Expected-Returns.pdf#page=20)
explicitly identifies expense `[14-65]`, income `[18]` and leverage `(5+9)/6`.
Its separate duplicate COGS/PPE item number does not invalidate these entries.
Use those expressions as historical source targets to investigate, without
declaring an unreviewed modern provider mapping equivalent.

Historical vendor distinctions and their primary links are summarized in PR #20.
They support technical review; WRDS/Compustat access is not a dependency.

## Resolve three bridges without changing v1

For expense, collect pure depreciation and the paper-construction components as
distinct candidates. Income-statement versus cash-flow presentation, intangible
amortization, depletion and other components require an explicit inclusion map.
Do not subtract similarly named fields until their scopes and overlap are known.
Do not feed a paper-construction candidate into v1's pure-depreciation input.

For debt, establish noncurrent classification and finance/capital-lease inclusion
from the source filing. Check whether a reported aggregate already includes each
component before adding it; current maturities must not be counted twice with
current liabilities. AV's [documented noncurrent debt](https://documentation.alphavantage.co/FundamentalDataDocs/gaap_documentation.html)
excludes capital leases. Broad current debt cannot automatically stand for the
current portion of long-term debt. Operating leases are a distinct scope question.

For income, reconcile attribution, discontinued/extraordinary items, special
items and dividend treatment with the original filing. Record CFO scope
separately; any alteration of the paper's accrual construction needs its own
method review. A continuing-income label, equality with cash-flow net income,
or an absent component does not establish the bridge.

## Review and acceptance

Engineering collects candidates and receipts under the fixed pilot. Research
reviews accounting mappings; it does not ask the user to choose an accounting
fact. Preserve qualified, nonmissing AV observations as primary and report
qualification gaps explicitly. Supplements require exact issuer, period, units,
currency, consolidation and version alignment. An unmatched month-end date stays
unmatched. Numeric agreement and undocumented tolerance cannot establish meaning.

After evidence resolves the targets, propose a separately named method version
and input contract if needed. Review independent fixtures whose depreciation,
amortization, depletion and lease components differ, plus missing, overlap, scope,
sign and version failures. The author example checks arithmetic; it does not
replace this reconciliation or reproduce every study preprocessing step.

This document authorizes no score, historical cutoff interpretation, backtest or
investment claim. Collection completion, source qualification, historical
availability and investment validation remain separate gates.
