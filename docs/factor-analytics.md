# Factor diagnostic arithmetic

The functions in `factor_research/analytics.py` calculate descriptive diagnostics.
Their inputs remain caller-owned: historical eligibility, information availability,
security links and holding intervals must already be established under the
[financial-quality research protocol](financial-quality-study.md).

## Bucket direction and formation

`factor_monotonicity` assigns quantile buckets from all nonmissing factor scores
on each date shared with the return panel. Higher-numbered buckets have higher
factor scores. The spread is the highest-score bucket's mean return minus the
lowest-score bucket's mean return. Its sign therefore preserves the predeclared
factor direction. For example, factor scores `[1, 2, 3, 4]` and forward returns
`[0.04, 0.03, 0.02, 0.01]` give a two-bucket spread of **-0.02**.

The previous maximum-minus-minimum calculation selected the best and worst
realized bucket returns after observing them, including interior buckets, and
could never report a negative spread. Previously stored summaries require
recalculation; the code does not rewrite them automatically.

Return availability does not affect quantile boundaries or asset assignments.
Factor-panel assets absent from the return panel remain assigned. A bucket mean
requires a return for every assigned member; an incomplete bucket stays missing.
Missing labels never become zero returns. Dates with fewer observations than
requested buckets, or ties that collapse the requested quantile bins, also stay
missing. Ties are not broken by arbitrary asset order.

The spread series retains all shared dates, including undefined observations.
The second return value contains each bucket's mean across its defined dates;
different buckets may therefore have different observation counts. It is not a
same-date portfolio comparison. The wrapper reports
`bucket_spread_observed_dates` and `bucket_spread_missing_dates` alongside the
mean spread so unavailable dates remain visible.

## Selected-leg diagnostic

`long_short_returns` selects its upper/lower tails using factor scores alone,
then reads the corresponding forward returns. A missing selected member makes
that date's diagnostic missing; no other asset replaces it. A missing unselected
return does not affect either tail. Overlapping long and short selections from
tied scores leave the date missing. Percentile fractions must be finite,
positive, and sum to less than one.

This helper supplies equal-weighted leg arithmetic. It does not implement
execution, drift, costs, borrow, corporate actions or delisting treatment. The
convenience wrapper retains its legacy daily annualization/window assumptions;
these corrections do not make it frequency-aware or certify monthly market
inputs. Undefined dates must not be interpreted as zero-P&L trading dates.

## Coverage and wealth baseline

Coverage uses every date and asset declared in the supplied factor panel.
Permanently missing assets and completely missing dates remain in the denominator.
For two dates and three assets with just one observed value, coverage is `1/6`
and the share of completely missing dates is `1/2`. An all-missing nonempty panel
has zero coverage. A zero-sized axis retains its declared size and produces
undefined rates because there is no panel denominator.

The bucket, selected-leg and coverage paths reject duplicate/null date or asset
labels and infinite observations. Missing numeric values remain missing and
caller-owned inputs are not mutated.

`max_drawdown` includes initial unit wealth in the running peak. Returns
`[-0.10, 0.05]` therefore have a maximum drawdown of `-0.10`, even though the
first stored wealth observation is already below one.

## Verification

`tests/test_factor_analytics.py` uses hand-calculated negative/middle-bucket
examples, missing-label/column perturbations, tied scores, sparse dates, declared
coverage dimensions and initial-loss paths. These are arithmetic checks, not
evidence of investment performance.
