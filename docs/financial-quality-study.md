# Financial Quality: Data Gate and Research Protocol

**Status: protocol and tested availability selector, not a completed alpha study.**
No real-data return result is claimed. This is a new, narrowly scoped follow-up
to earlier exploratory work, not a retroactive validation of that work.

## Question and locked starting specification

Does lower accrual intensity predict subsequent one-month equity returns after
controlling for sector, size, and value? Start with one predeclared signal:
negative (trailing-four-quarter net income minus operating cash flow) / average
total assets. Handle cash-flow YTD-to-quarter conversion within fiscal years;
do not silently treat YTD fields as quarterly flows. Require positive assets,
consistent units/currency, and actual publication times for every input.

## Why the existing extracts cannot answer it yet

A local source audit found fiscal-period dates but no verified release/filing
timestamps in the available main extracts. The old merged research panel also
contains precomputed multi-year forward returns and full-sample-derived scores.
Those scores will not be reused. Historical eligibility, delistings, and
point-in-time revisions have not been established. A fixed reporting lag is a
sensitivity assumption, not proof of historical availability.

Original vendor records remain private. This repository contains no vendor
extract, team notebook, or copied team report for this study.

## Required input contracts before running market results

- Stable security/company identifiers with effective-dated links; historical
  investable membership including delisted securities, not today's S&P 500 list.
- Original filing versions, fiscal-period end, publication timestamp and timezone,
  and version/revision availability; documented net-income, cash-flow and asset units.
- Total returns including corporate actions and delisting treatment, market cap,
  sector/value controls with their own availability, and an explicit trading calendar.
- Clear source/licensing terms and documented redistribution restrictions.

The reference [`fundamentals_asof`](../src/systematic_alpha_lab/factor_research/availability.py)
requires `available_at`: it never substitutes the fiscal-period end. It chooses
the newest fiscal period then its newest available revision, so a late revision
of an older period cannot replace newer-period information. Missing matches stay
missing. This row-wise implementation is for correctness review, not scale.
It cannot verify that the supplied timestamps or universe are themselves genuine.

## Evaluation after the data gate passes

1. Fix the time split before inspecting returns: earliest 60% of usable months for
   development, next 20% for validation, final 20% for testing; record calendar
   boundaries and input hashes. Exclude training observations whose holding periods
   overlap the next segment. Historical results are not a prospective live holdout.
2. Form monthly signals after the applicable filings are public, then trade at
   the next eligible execution timestamp. Fit transformations only with information
   available at formation. Cross-sectional ranks must be computed separately each date.
3. Compare the single raw signal with sector/size/value-adjusted versions and simple
   baselines; do not select among dozens of composites using test-period performance.
4. Report coverage, monthly rank IC, uncertainty allowing temporal dependence,
   sector exposure, and rolling/subperiod stability. Preserve missingness and failures.
5. Use a proven portfolio backtesting engine for any portfolio extension; model
   weight drift, tradable prices, fees, turnover, borrow assumptions and constraints.
   IC alone is not tradable P&L. Predeclare 0/10/25 bps one-way cost scenarios as
   sensitivity assumptions, not measured transaction costs.
6. Publish a short evidence-linked memo even if the effect disappears. Do not
   describe a synthetic demo or an assumed reporting lag as validated market alpha.

## Tests already implemented

Availability/revision selection, no backfill before release, asset isolation,
missing timestamp rejection, duplicate-version rejection, future-mutation
invariance, and empty/missing data behavior. Separate toolkit tests check explicit
forward-return alignment and future-price invariance of the small synthetic factors.
