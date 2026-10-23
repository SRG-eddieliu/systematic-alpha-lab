# Integrity definition gaps: Adjusted M and the fixed composite

Prepared 2026-10-22, America/Toronto, under SRG-RD-002. This is a dated source
audit, not a replacement specification or a second live project checkpoint.
The written five-factor recipe has been located. Its operational transforms
and executable lineage, including the Adjusted M1 generator, remain unresolved.

## Verified code baseline

[PR 14](https://github.com/SRG-eddieliu/systematic-alpha-lab/pull/14) was
independently reviewed and merged at
`4f72449c3e12a21e78a10a92ca95be9888f72efa`. The reviewed head was
`18f0341c6f17d9db2eeef237a5a563cf763a7004`; both have tree
`876652e86513f8d74b90b02b80f869b0ee474343`.

The review reran all 547 tests, seven examples with network calls prohibited,
and the authorized private-input Beneish audit. The replay matched the
[published aggregate receipt](validation-beneish-sample-2026-10-22.json):
18 input rows, 15 targets, zero eight-ratio error, maximum M error
`8.881784197001252e-16`, maximum legacy-logistic error
`2.220446049250313e-16`, and all 15 flags matching at absolute tolerance
`1e-10`. Independent code and evidence reviews found no blocking defect.
The same head's [Python 3.10/3.11 CI](https://github.com/SRG-eddieliu/systematic-alpha-lab/actions/runs/39880208620)
passed. See the [original validation record](validation-beneish-2026-10-22.md)
for commands and policies. These checks establish the bounded legacy quarterly
arithmetic, not an annual-model adapter, calibrated probability or market alpha.

## Distinct report versions

Two private report versions have the same subject but different bytes and
content. No evidence establishes that either supersedes the other.

| Source role | Bytes | SHA-256 | Recovered statement |
| --- | ---: | --- | --- |
| Previously retained Library report | 174,407 | `7fd876d1cd5f6557184439177dfb81d8b1762ee630334507e4a3dacde53c2aa4` | Names five normalized components with equal weights; does not identify the Adjusted M variant or individual signs. |
| Located twenty-page report, dated July 2025 | 2,134,106 | `7c63411b4ead3f97303d6f9b6acfe090d670bb7e348d93621f3ad31bf9898c0b` | Selection table identifies Adjusted M1; section 4.5 states signed coefficients of magnitude 0.2. Appendix E supplies a different, broader implementation. |

In the twenty-page version, the selection table is on physical page 6 / printed
page 5, the formula on physical page 8 / printed page 7, and the higher-is-better
statement on physical page 9 / printed page 8. These pages were visually
checked, including the selection-table image. Its written recipe is:

```text
IS = 0.2 Chi_d2 - 0.2 Chi_d1 + 0.2 AdjM1 - 0.2 R2_L1 + 0.2 R2_L2
```

`AdjM1` here binds the formula's Adjusted M symbol to the selection table's
Adjusted M Score1. It does not define that input's calculation. The formula
also does not establish whether its symbols mean raw fields, signed z-scores
or other transformed quantities. It must not be implemented by silently
choosing one interpretation.

## What the saved implementation actually does

Q04 and its hidden checkpoint are byte-identical, SHA-256
`0e369846b420fdc1492d19bc05e6b228aa4984cb8c8f6852cbb809c8aec061e9`.
They do not provide separate versions of the composite. The twenty-page
report's Appendix E, physical pages 18–20 / printed pages 17–19, contains the
same broader construction recipe:

- Begin with 19 candidate names, keep columns present in the panel, and apply
  absolute-correlation pruning at 0.8.
- Use pooled whole-panel z-scores with default population standard deviation
  (`ddof=0`). Negate M, Adjusted M1 and Adjusted M2; leave the other retained
  factors positive. There is no per-date or training-only fit.
- Fill missing normalized values with zero and average all retained columns
  for `integrity_equal`. Also fit whole-panel PCA and construct a separate
  weighting from maximum absolute correlations with future 1Y/3Y/5Y returns.

The saved run retained **16** available candidates. The three R-squared
summary columns were absent, and stored stdout reports an empty correlation
drop list. They were not three factors removed for high correlation.

A read-only aggregate check of the saved result (SHA-256
`0befad0b118dc04bd4b6ee27a64f369ff7df03bea628619f0377e67568e7d93f`)
found 19,228 rows, 72 columns and 16 normalized factor columns. All 19,228 saved
`integrity_equal` values match the explicit sixteen-column mean at absolute
tolerance `1e-10`, maximum error `6.661338147750939e-16`. All 16 normalized
columns also align with their known signed pooled z-scores within that
tolerance. This checks an already explicit recipe against saved output; it
does not fit a five-factor formula or replay the complete historical pipeline.
See the [aggregate evidence](integrity-definition-gap-evidence-2026-10-22.json).

Three unresolved links prevent treating this as the reported fixed composite:

| Link | Conflict or missing evidence |
| --- | --- |
| Component selection and signs | The body selects five terms; Appendix E and saved output use sixteen. Under direct raw-field correspondence, the report's negative Chi2 D1 / R2 Lag1 and positive AdjM1 differ from Q04's positive / positive / negative z-scores. An earlier transform could change that interpretation, but none is documented. |
| Transformation and missingness | No source connects the fixed recipe to a normalization universe, fit window, standard-deviation convention, outlier treatment, transform order, missing-component policy or output column. Q04's own rules cannot be assigned to the fixed recipe by assumption. |
| Frequency and meaning | The report describes firm-year scoring; Q04 uses ticker/fiscal-quarter rows. Q04's R-squared values come from separate NI-on-lagged-YTD-CFO regressions over prior eight-row windows, not factor-to-return R-squared or a joint multi-lag regression. Annual aggregation and contiguous-quarter/stable-company contracts remain unproven. |

Q04 also filters observations using future-return availability before its
pooled transformations. Its saved arithmetic is not out-of-sample evidence.

## Adjusted M: what the expanded search establishes

The audit covered 14 source notebooks including seven hidden checkpoints
(204 actual code cells), five XLSX formula sets and 13 CSV schemas. A separate
scan covered 255 code/document/configuration files across two earlier code
trees, including ten notebooks and 98 code cells. Neither scan located the
Adjusted M1/M2 generator or the assembly/export code for Q04's initial table.
The early outline and field-specification documents add no such definition.
Negative findings are bounded to the recorded files and actual cell sources;
they do not exclude another machine, cloud copy or unexamined history.

The initial input table already contains `adj_M_score1/2`; its fingerprint is
`0775b0d14b526df37e9968be1bb4a1dee3ffe606b041e270728a1bd7faf71ba5`
(393,310,784 bytes, 46 columns). The columns persist in later saved tables.
Field presence and subsequent normalization establish consumption, not the
formula or provenance that created the values.

An independently inspected verification workbook (SHA-256
`77c5d09ab02eae2d4ce6d0494e3d7680b42772003895f0c3922dbb00d1f81285`)
adds a useful but unbound lead. Its first worksheet labels NI as `ibq`, CFO
as `oancfq` and assets as `atq`; cell H9 uses `4.679*(D11-D12)/D5`, the
NI-minus-quarterly-CFO contribution, and H13 applies `NORMSDIST` to the total.
These differ from Q07's simplified balance-sheet TATA and hand-set logistic
mapping. No formula, label or export chain binds the workbook variants to
`adj_M_score1` or `adj_M_score2`. They cannot be renamed as those definitions.
The report's descriptions of scale/accrual adjustments are also insufficient
to define either transformation.

No original notebook or Excel calculation was executed, no source was edited,
and no replacement factor was inferred from output values or future returns.
Original reports, code cells, source tables and detailed local evidence remain
private. This repository contains original descriptions, hashes and aggregate
checks only.

## Minimum evidence needed next

1. **Adjusted M lineage first:** locate a source version or method record
   explicitly creating each named variant, including fields, denominators,
   coefficients/transforms, signs, quarterly/YTD/TTM basis, lags, units and
   missing/zero/outlier rules. Connect it to the fingerprinted initial table
   through an assembly/export record and stable company/period keys.
2. **Fixed-composite contract:** connect the five written terms to exact
   transformed inputs. Specify scoring frequency, component directions,
   normalization fit universe/window, missingness and output identity. Resolve
   the body/appendix/output disagreement and the Benford input/statistic
   lineage explicitly.
3. **Independent bounded validation:** once a source definition is recovered,
   predeclare a small set of inputs and compare each intermediate component
   before a composite result. Retain source/code/config fingerprints and
   aggregate errors. Historical availability and market testing remain
   separate gates.

If the original generator cannot be recovered, implementing a version derived
from the report requires an explicitly selected new operational specification.
It must carry a new version and be recorded as a new definition. Fitting saved
scores, choosing a plausible Excel variant, or choosing signs using returns
would not restore the historical definition.
