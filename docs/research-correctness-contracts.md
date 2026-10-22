# Coefficient and study-split contracts

These contracts cover numerical helpers and a monthly study-design reference.
They do not establish data provenance, historical availability or investment
performance. The [financial-quality protocol](financial-quality-study.md) still
governs the real-data entry gate.

## Covariance directions and legacy names

| API | Calculation | Interpretation |
| --- | --- | --- |
| `weight_gmv_direction` | Pseudoinverse covariance times ones; optional absolute values; normalize by signed sum | Coefficient direction; absolute values and singular covariance do not solve constrained minimum variance |
| `weight_mvo_direction` | Regularized pseudoinverse covariance times expected coefficients; optional negative clipping; normalize by gross absolute weight | Coefficient heuristic, with no risk-aversion argument |
| `weight_gmv` | Compatibility wrapper around `weight_gmv_direction` | Same heuristic; no risk-parity guarantee |
| `weight_mvo` | Compatibility wrapper around `weight_mvo_direction` | Requires positive finite `risk_aversion` for compatibility; changing it has no effect on normalized weights |

For a positive scale `lambda`, dividing a direction `d` by `lambda` and then
normalizing by its absolute sum cancels the scale exactly. The previous docstring
incorrectly claimed that increasing risk aversion increased the variance penalty
in the final weights. The explicit direction API removes that misleading
argument; the compatibility wrapper preserves ordinary positive-scale results.
The alpha pipeline retains its `gmv`/`mvo` result keys and attaches
`weighting_kind = normalized_covariance_direction_heuristic`; its MVO result also
records `risk_aversion_effect = none_after_unit_gross_normalization`.

A hand-checkable counterexample is covariance `[[1, 2], [2, 9]]`. The signed
ones direction is `[7/6, -1/6]`; taking absolute values produces `[7/8, 1/8]`.
The feasible all-first-component allocation has lower variance than that
absolute-value result. A constrained optimizer remains a separate future feature.

Covariance axes must contain unique nonempty string names with matching sets.
Columns are aligned to the row order before arithmetic. Matrices must be finite,
symmetric and positive semidefinite, allowing scale-relative floating-point
roundoff. The pseudoinverse discards eigenvalues at the same roundoff scale;
zero directions produce an empty result. Indefinite pairwise estimates require
an explicit covariance-model decision; these helpers raise instead of silently
repairing them or returning arbitrary weights. Nonnegative finite ridge
regularization is applied only after covariance validation.

MVO uses the intersection of expected-coefficient and covariance names, in
covariance order. Names outside that intersection receive no output weight.
All supplied coefficients must be finite. Equal weighting rejects repeated names;
regression coefficient normalization avoids overflow in the absolute sum.
IC weighting requires a positive integer window and ordered unique observation
labels, using the last nonmissing supplied observations. The caller must have
already restricted them to information available at the relevant decision.

The legacy Bayesian helper is a linear blend on the equal-weight map's explicit
universe. Names absent from that map are outside its output. Its blend fraction
must be in `[0, 1]`; signed cancellation can reduce gross exposure because it does
not renormalize the blend. This arithmetic is not a calibrated posterior model.

## Freeze a monthly experiment

`factor_research.study_split.monthly_chronological_split` takes an observation
table with these fields and named source SHA-256 hashes:

| Field | Contract |
| --- | --- |
| `asset_id` | Nonempty stable traded-security identifier supplied by the caller |
| `feature_available_at` | Public availability of every feature input/dependency, on a consistent source basis |
| `decision_at` | Common decision timestamp for that monthly cross section |
| `holding_start_at`, `holding_end_at` | Explicit execution and holding-period boundaries |
| `label_available_at` | Time the complete realized label could be known, including any delayed component |

All timestamps require explicit timezone information and normalize to UTC.
The required order is `feature <= decision < holding_start < holding_end <= label_available`.
Duplicate security/decision rows and multiple decisions in a UTC decision month
raise. The reference uses UTC decision months; callers must establish their own
actual market schedule and historical eligibility before constructing this input.

The helper sorts distinct usable decision months and fixes boundaries at
`floor(3N/5)` and `floor(4N/5)`, requiring at least five months. Month counts,
rather than counts of securities or observations, determine the 60/20/20 split.
Missing months are not synthesized. Row order and factor/return values do not
determine the split. Adding or removing months requires a new recorded plan.

Development and validation observations are marked `purged` if their complete
labels become available at or after the next segment's first decision. This
also removes overlapping holding periods because label availability cannot
precede holding end. Touching a boundary is conservatively excluded. Delayed
label publication can require purging even after a holding period has ended.
A segment with no retained rows raises; purged observations remain visible with
an exclusion reason and must be filtered explicitly before using a segment.

The returned manifest records calendar boundaries, assigned/purged/retained
counts, a canonical timing/identity hash and the caller's source hashes. It does
not hash unspecified feature/return payloads or verify that caller-supplied
source hashes match external files. Preserve the complete source files and
verify those hashes in the ingestion/replay layer. Freeze the manifest before
model selection. Use development for fitting, validation for selection and test
for final evaluation; a historical test segment is not a prospective holdout.

This reference does not fit models or retrofit the legacy rolling ML path with
these guarantees. Missing actual publication, execution or label-availability
timestamps must be resolved upstream; they are not replaced with period ends
or a fixed lag here.

## Offline verification

`tests/test_weighting.py` checks named-axis invariance, hand-calculated
directions, legacy scale cancellation, malformed covariance/parameter rejection
and finite coefficient normalization. `tests/test_study_split.py` checks month
weighting, label-boundary purging, delayed publication, future-return mutation,
timezone equivalence, immutable inputs and missing/ambiguous metadata rejection.
`examples/research_contracts_demo.py` is synthetic, network-free and performs no
model fitting or historical return study.
