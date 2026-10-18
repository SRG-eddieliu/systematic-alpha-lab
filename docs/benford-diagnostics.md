# Benford diagnostics: arithmetic and information timing

Repair/execution date: 2026-10-18. This repairs an existing financial-quality
module; no new product, return study or fraud model is introduced.

## Mathematical definition

[NIST's significant-digit definition](https://xlinux.nist.gov/dads/HTML/benfordslaw.html)
gives `P(D1=d)=log10(1+1/d)`. Applying its general joint leading-digit law to the
90 two-digit bins and summing over the first digit gives:

`P(D2=d)=sum(log10(1+1/(10*k+d)), k=1..9)`, for `d=0..9`.

This marginalization is the implementation's derivation from the general rule.
The old code included only `k=1`, producing weights summing to approximately
0.30103. Both repaired distributions sum to one; tests also check the independent
90-bin joint construction and known marginal probabilities.

Extraction parses the represented decimal coefficient without integer truncation,
float conversion or logarithmic rescaling. `0.0034`, `34` and `-3.4e20` give digits
3 and 4. Negative values use the magnitude. Zero and missing/nonfinite/unparseable
values are separately counted and excluded. Mathematical digits include implicit
zeros: `9`, `9.0` and `9e3` have second digit 0. This is a numeric convention, not
a statement about measurement precision. String/Decimal inputs preserve magnitudes
outside float range; upstream rounding cannot be reversed.

Pearson discrepancy uses counts: `sum((count-n*p)^2/(n*p))`. Expected probabilities
must be positive and normalized. Empty valid samples produce missing scores.
Sample size affects the statistic, so coverage must accompany comparisons.

## Descriptive interpretation

Outputs include total, valid-nonzero, zero, invalid and negative counts; two
discrepancies; minimum expected counts; and `cell_count_screen_d1/d2`. These
screens only check whether every observed and expected cell has count at least
five. They do not establish independence or that the selected amounts should
follow Benford's law. Related statement totals are not generally independent.

The [SciPy Pearson-test documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.chisquare.html)
describes independent categorical observations and the small-cell restriction.
The module returns no inferential p-value, fraud probability or manipulator label.
A statistic computed from a few statement line items does not establish a valid
asymptotic test.

## Snapshot interface

`benford_snapshot_diagnostics(statements)` requires `asset`, `period_end`, `field`
and `value`, with one row per company/period/field. The caller selects appropriate
financial amounts, stable company IDs and a consistent monetary basis. Numeric
IDs, fiscal labels and duplicated totals are not automatically selected. Ambiguous
duplicate fields are rejected. Output has status
`snapshot_only_availability_unverified` and no `available_at`.

## Explicit as-of reference

`benford_asof_diagnostics(filings, decisions, fields=[...])` additionally requires
`available_at`, `currency` and `unit` for every field version. Decisions contain
`asset` and `decision_at`. Release/decision timestamps must be timezone-aware;
naive dates are rejected rather than interpreted as UTC. Period ends remain
period identifiers, not substitute publication timestamps.

At each decision the reference implementation:

1. Excludes versions released after the decision.
2. Selects the newest available version of each field in each period.
3. Chooses the newest period with published records for every declared field.
   A partially published new period leaves the prior complete period in use;
   without a complete period, the score stays missing.
4. Requires a common currency/unit. A published missing value remains missing;
   it never restores a superseded nonmissing amount.
5. Reports descriptive scores, selected period and latest input availability.
   A late older-period revision cannot replace a newer complete period.

Identical-timestamp duplicate versions and undeclared fields are rejected. Status
`supplied_timestamp_asof` describes selection using supplied metadata. It does
not verify authenticity, reconstruct missing vintages, resolve historical security
links or establish an execution policy. Decisions must already include the
caller's processing/execution delay. This row-wise implementation is a correctness
reference, not a scalable database or a validated strategy.

## Legacy daily-factor migration

Previously `BenfordChiSquareD1/D2` reindexed fiscal-period scores onto price dates,
forward-filled and shifted one row. This could expose statements before release;
periods absent from the trading calendar could also disappear. A one-row shift
does not establish publication timing.

Class identifiers remain, but **`compute`, `compute_raw_factor` and `post_process`
now raise an actionable `ValueError`**. `compute_snapshot` returns descriptive
period panels using explicit quarterly `period_type`, rejects duplicate quarters,
preserves loader frames and never loads prices or produces daily signals.

Default factor/composite definitions retain the identifiers for provenance. A batch
requesting them now stops at the timing error; it does not silently drop them or
fill from other companies. Migrate explicitly to the as-of API with genuine
field-version metadata and stable identifiers before adding market integration.
Do not rename fiscal-period dates to `available_at`.

## Reproduction and verification

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python examples/benford_diagnostics_demo.py
```

Local environment: Python 3.11.14, NumPy 2.2.6, pandas 2.2.3, SciPy 1.14.1,
pytest 9.0.1. **106 tests passed**: 53 new Benford cases, one key-audit fixture,
and the previous 52 cases. Coverage includes distributions, fractional/scientific/
extreme values, SciPy statistic agreement, exclusions, release boundaries, revisions,
partial publication, timezones, missing metadata, future-mutation invariance and
the legacy interface gate.

The four-amount synthetic demo gives discrepancies approximately 6.29971938 and
5.73343251. Its count screen fails. The score is missing one minute before the
supplied release and present exactly at it. These are software checks, not market
or fraud-detection evidence. Hosted CI status is recorded after publication.

## Input readiness

Real-data source audits and any derived statistics belong in private research records. This public repair contains code, mathematical definitions and synthetic verification only. It does not establish authentic publication timestamps, original vintages, source units or valid market results. Apply the [study protocol](financial-quality-study.md) before market evaluation.
