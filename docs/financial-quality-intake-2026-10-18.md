# Financial-quality source consolidation

Review and execution date: 2026-10-18. Portfolio role: signal-research module of
Systematic Alpha Lab. No additional standalone product repository was created.

## Accepted implementation boundary

[`quarterly_accrual_diagnostic`](../src/systematic_alpha_lab/factor_research/financial_quality.py)
implements the arithmetic of the single accrual signal already specified in the
[study protocol](financial-quality-study.md):

`accrual_quality = -(sum(last 4 quarterly NI) - sum(last 4 quarterly CFO)) / ((assets[t-4] + assets[t]) / 2)`.

Higher values mean lower measured accrual intensity under this definition. This
direction is a research hypothesis, not an observed return finding.

The function is explicitly a **single-snapshot diagnostic**. It does not generate
an availability timestamp, trade date, investment probability or portfolio return.
It is separate from the existing annual `Accruals` factor and its period-end-indexed
loader. This work does not certify that older factor as point-in-time safe.

### Input contract

| Field | Meaning |
| --- | --- |
| `asset` | Stable company identifier as a nonempty string, rather than a mutable ticker |
| `fiscal_year`, `fiscal_quarter` | Integer fiscal labels; quarter is 1 through 4 |
| `period_end` | Actual period end, increasing with fiscal quarter labels |
| `currency`, `unit` | Explicit common monetary basis for all three amount fields; normalize changes before calculation |
| `net_income` | Quarterly net income, not annual or fiscal-year-to-date income |
| `operating_cash_flow_ytd` | Fiscal-year-to-date operating cash flow |
| `total_assets` | Period-end total assets |

One row per company/fiscal quarter is required. Source versions or formats must
be resolved using documented provenance before invocation. Duplicate quarters
raise an error; they are not averaged or arbitrarily kept. Missing amounts remain
missing, infinite amounts are rejected, and currency/unit changes require explicit
normalization. Merely assigning a unit label does not verify source units.

Q1 cash flow equals that fiscal year's YTD amount. Q2–Q4 require the immediately
preceding quarter of the same fiscal year; missing predecessors yield missing
quarterly flows. Negative cash flow is valid. Four consecutive quarterly flows
and positive opening/closing assets are required. The asset denominator needs
five consecutive quarter records. Fiscal labels govern conversion, including
noncalendar fiscal years. Caller-owned inputs are left unchanged.

## Source findings

Seven original notebooks are preserved outside this repository. Their immutable
content hashes and neutral roles are in the [source manifest](financial-quality-source-manifest.json).
The originals, notebook outputs and vendor extracts are not distributed here.

| Source role | Observed issue | Consolidation decision |
| --- | --- | --- |
| Q03: cash-flow preparation and leading-digit exploration | Cash flow uses a company-wide `diff()` and special-cases only the first company row; later fiscal Q1 values subtract prior-year YTD | Replace this conversion in the accepted slice with fiscal-year resets and predecessor checks |
| Q04: regression/composite exploration | Global z-scores/PCA and maximum absolute correlations with 1/3/5-year returns determine the composite weights in the same panel | Do not import those scores as prospective signals or reuse the returns for signal construction |
| Q07: merged signal exploration | Current constituent list, ticker/fiscal-quarter joins, adjacent-row lags and logistic transforms named probabilities | Do not import the merge, automatic universe selection or probability claims |
| Q06: whole-extract leading-digit diagnostic | Numeric-column auto-selection includes identifiers/fiscal labels; positivity and global IQR filters affect all selected fields | Require explicit financial field definitions rather than automatic numeric-column screening |
| Q01/Q02/Q05: return and portfolio exploration | In-sample comparisons, full-panel bucketing and fixed ticker groups do not establish a historical formation/execution process | Preserve as source lineage; no historical strategy result reproduced or endorsed |

The pre-existing Benford factor is also **outside this verified slice**: its
second-digit expected weights do not sum to one, integer conversion mishandles
fractional magnitudes, and its fiscal-period index does not establish information
availability. These require a dedicated repair before use. No fraud probability
or market result from that implementation is certified by this consolidation.

## Actual input audit

The read-only source audit recorded the following aggregates, without exporting
company rows. Hashes identify exact snapshots; they do not establish data rights,
correctness or historical availability.

| Private input role | Rows | Rows involved in duplicate company/fiscal-quarter keys | Rows with missing key fields |
| --- | ---: | ---: | ---: |
| Cash-flow/leading-digit extract | 657,422 | 820 | 134 |
| Ratio-analysis extract | 724,081 | 306 | 0 |

Both extracts report the same INDL/C/D/STD source format combination and USD
currency. Dropping missing keys from the first leaves 708 rows involved in
duplicate keys, so format filtering alone does not resolve the ambiguity. These
are affected-row counts, not duplicate-group counts. Monetary units and genuine
release/version timestamps remain unverified. No actual-data accrual scores,
returns, ICs or portfolio results were produced in this pass.

## Verification

Environment: Python 3.11.14, NumPy 2.2.6, pandas 2.2.3, pytest 9.0.1.

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python examples/financial_quality_snapshot_demo.py
```

Actual local result: **52 passed**, including 25 new financial-quality cases.
The new cases exercise a hand-calculated accounting identity, fiscal-year resets,
negative/missing cash flows, skipped quarters, noncalendar fiscal labels, stable
company isolation, immutable inputs, future-mutation invariance, duplicate/version
rejection, monetary-basis validation and denominator requirements.

The offline example is entirely synthetic: 8 statement rows, 4 arithmetic-ready
rows; the first 2021 quarterly CFO is 5 rather than the incorrect cross-year
difference of -31. Its last diagnostic is approximately -0.05333333. These values
only verify the calculation. Existing CI runs the complete pytest suite on Python
3.10 and 3.11; hosted execution status is recorded separately after publication.

## Remaining gate

Resolve duplicate source versions, verify units and quarterly income definitions,
and obtain real filing availability/original vintages before any historical signal
formation. Historical universe, security links and total-return data also remain
required. Computing this diagnostic on a restated snapshot and assigning an
assumed reporting lag would not satisfy that gate. A publication-time selector
alone cannot reconstruct missing historical vintages.
