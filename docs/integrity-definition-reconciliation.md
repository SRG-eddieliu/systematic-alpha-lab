# Integrity definition reconciliation

Prepared 2026-10-22, America/Toronto. This records source restoration and
arithmetic verification under SRG-RD-002. It does not establish a market alpha,
a calibrated fraud classifier or a new composite specification.

Seven recovered private notebooks Q01–Q07 match both their original local
files and their previously retained source manifest, byte for byte by SHA-256.
Original notebooks, reports and licensed input rows remain outside this
repository. The following descriptions are an independently written account
of their behavior; no original notebook is being republished.

## Report, recovered implementation and accepted scope

| Component | Report description | Recovered implementation | Current decision |
| --- | --- | --- | --- |
| Beneish | Eight-ratio M-score / Adjusted M | Q07 applies the eight coefficients to adjacent retained quarterly rows; TATA is `(change current assets - change current liabilities) / current total assets`. Its threshold and sigmoid are hand-set. | Preserve exact arithmetic as `legacy_q07_quarterly_proxy_v1`, with explicit validity checks. It is not the published annual model. |
| Adjusted M | A transformed M-score contributes to the composite; the located twenty-page report selects Adjusted M1 | Q04 and the additionally located Q08 consume existing fields. Expanded local versions and reachable Git histories found no original generator or binding to the Excel variants. Q08's separate comparison branch labels a rename from M-score to M1 as an assumption. | Generation and upstream lineage remain unresolved; a rename, output fit or another transformation is not the definition. |
| Benford | First/second digit chi-square quantities | Q04 consumes precomputed fields; Q07 constructs a different first-digit financial-field distance, without the chi-square sample-size multiplier, then applies a custom sigmoid. Source lineage between these is unproven. | Existing corrected Benford diagnostics are separate. Recover the exact input pool and statistic definition before reconciling the original combined score. |
| Accrual quality | Net-income/CFO lag regression R-squared | Q04 fits separate single-variable `ibq ~ shifted oancfy` regressions inside an eight-row window, lag 0–4, and attaches output to the next row. It uses YTD CFO rather than the available quarterly CFO column. | Preserve this finding; decide flow alignment and window/sample rules before a replacement regression. It is not a joint distributed-lag model. |
| Income quality | NI/CFO and lagged CFO ratios | Q04 computes `ibq / shifted oancfy` after complete-case filtering; a row shift can skip missing quarters. | Quarterly NI/YTD CFO basis and lag continuity remain unresolved. |
| Integrity composite | The Library report names five normalized components; a distinct twenty-page report states signed coefficients of magnitude 0.2 and selects Adjusted M1 | Q04 uses sixteen signed pooled z-scores. Newly located Q08 explicitly selects five, fits full-panel MinMax, gives all five positive 0.2 coefficients, then averages by ticker/calendar year. Its normalized export matches the known-recipe input comparison. | Preserve three separate versions: report signed five, Q08 positive MinMax five, Q04 sixteen. Q08's downstream execution contract is recovered; Adjusted M, upstream assembly and the report direction disagreement are unresolved. Whole-panel transformations do not support out-of-sample claims. |

The located twenty-page report states `0.2 Chi_d2 - 0.2 Chi_d1 + 0.2 AdjM1 -
0.2 R2_L1 + 0.2 R2_L2`, with higher values intended to mean better integrity.
The [dated definition-gap audit](integrity-definition-gaps-2026-10-22.md)
distinguishes both report versions, the recovered written recipe and the
saved sixteen-factor arithmetic. The formula's input transformations,
normalization, missingness, scoring frequency and Adjusted M1 generator still
need an explicit source contract before rebuilding that reported composite.
The [history follow-up](integrity-source-history-2026-10-22.md) separately fixes
Q08's recovered MinMax execution contract; it must not be combined with the
report's signs and called the original formula.

## Published Beneish versus Q07

The unweighted eight-ratio coefficients are:

```text
M = -4.840 + .920 DSRI + .528 GMI + .404 AQI + .892 SGI
    + .115 DEPI - .172 SGAI + 4.679 TATA - .327 LVGI
```

The [author's current calculator](https://apps.kelley.iu.edu/beneish/mscore/mscoreinput)
uses the 2013 cash-flow version and comparable consecutive annual statements.
An explicitly prepared TTM comparison requires two year-apart TTM windows,
not two adjacent quarterly flows. The 1999 and 2013 accrual definitions differ:

- 1999 balance-sheet accruals adjust changes in current assets and liabilities
  for cash, current long-term-debt maturities and income taxes payable, then
  deduct depreciation/amortization, divided by current total assets.
- The 2013 version uses income before extraordinary items minus operating cash
  flow, divided by current total assets. Field equivalence must be verified;
  ordinary net income and D&A are not automatically accepted proxies.
- Q07 instead uses only `(change current assets - change current liabilities) /
  current total assets`, on adjacent quarterly observations.

The seven other Q07 ratios are conventional algebra applied to that different
quarterly information set. Its `M > -2.22` rule is retained only as a historical
choice. The [author's Sunbeam example](https://apps.kelley.iu.edu/Beneish/Content/Examples/SunbeamExample.pdf)
illustrates a -1.78 cutoff. Q07's `sigmoid(M + 2.22)` is a legacy logistic score,
not a Beneish probability. The published estimation is probit, and even a
model-implied normal-CDF value would require population/calibration caveats.

The new score function supplies raw linear arithmetic only: it does not
reproduce the original estimation population's winsorization or selected
neutral-value treatments, estimate fraud probabilities, select a cutoff, or
assemble an annual/TTM provider adapter. Raw ratios remain inspectable.

Primary references: [Beneish 1999 / DOI 10.2469/faj.v55.n5.2296](https://rpc.cfainstitute.org/research/financial-analysts-journal/1999/the-detection-of-earnings-manipulation),
[Beneish, Lee and Nichols 2013, Appendix A](https://cpb-us-w2.wpmucdn.com/sites.udel.edu/dist/a/855/files/2020/07/Earnings-Manipulation-and-Expected-Returns.pdf),
and the author-hosted calculator/example above.

## Implemented restoration

`systematic_alpha_lab.factor_research.beneish.beneish_m_score` accepts eight
explicitly named ratios. `legacy_q07_quarterly_proxy` accepts one caller-selected
current/previous company-quarter pair and the ten documented monetary fields.
It preserves the original formulas, returns each component, and refuses a
cross-company pair, nonconsecutive fiscal quarter, missing/nonfinite amount,
zero denominator or nonfinite result. Invalid flags remain `None`.

Currency and unit conflicts reject a pair. Missing declarations are reported
as unverified; caller declarations do not authenticate a source. The caller or
source adapter must resolve duplicate versions before selecting a pair. No
input is modified, downloaded, filled, annualized or joined to market returns.

The public synthetic example runs without credentials:

```bash
python examples/beneish_reproduction_demo.py
```

For an authorized private copy of the original CSVs:

```bash
python examples/audit_legacy_beneish.py \
  --raw /private/path/raw_data_beneish.csv \
  --saved /private/path/merged_beneish_benford_results_full.csv \
  --output /private/path/new-audit-receipt.json
```

The audit uses a predeclared three-company/six-quarter slice, reads amounts
from the raw source, checks one-to-one stable company/date/fiscal keys and
source amount agreement, then compares 15 new calculations to saved outputs.
Original files, optional row-level outputs and the full local receipt remain
private. A public aggregate receipt removes local paths/mtime and retains only
hashes, field mappings, policy, coverage, tolerance and errors.
The sample was chosen for unique consecutive inputs, not returns or a favorable
M-score. Numerical reproduction does not validate the source or research design.

## Remaining work

Choose and document a standard annual/TTM specification only after the legacy
restoration is understood. Verify income/flow/stock and depreciation field
semantics, missing-data policy and source versions, then test that specification
independently. Adjusted M generation and the fixed reported composite's
operational transforms and lineage remain unresolved; its written component
selection, signs and weights have been located in one report version.
Historical publication times, dated security links, membership including exits,
returns, controls and execution calendars retain their existing research gates.
