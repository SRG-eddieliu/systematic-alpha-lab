# Integrity restoration and Beneish verification — 2026-10-22

Executed after PR 13 merged at
`da4db67c84b203a3b4f14c7570e30fa7dc7160bb`. This is a dated verification
record, not a second live research checkpoint. See the
[definition reconciliation](integrity-definition-reconciliation.md) and
[aggregate machine-readable receipt](validation-beneish-sample-2026-10-22.json).

## What was checked

The recovered Q01–Q07 notebooks match their retained original-source hashes.
The relevant Q04 hash is
`0e369846b420fdc1492d19bc05e6b228aa4984cb8c8f6852cbb809c8aec061e9`;
Q07 is `d8191cc510d4957e3a53477405ef9fcafb64c98f9c22434bc18ad7628ef3f359`.
Their code was inspected, not executed. Original source material remains private.

- The author's public Sunbeam ratios give **M = -1.8840350** at their displayed
  precision, agreeing with the source's rounded **-1.884**. This independently
  checks the eight-ratio linear coefficients; it does not validate Q07's
  quarterly monetary definitions.
- A fixed private sample selects AAPL, MSFT and IBM, FY2018Q4–FY2020Q1: **18
  input rows**, with one warm-up quarter per company and **15 target rows**.
- All **18 stable company/date/fiscal keys** and currency declarations match
  between raw and saved inputs. All **180 monetary input comparisons** match.
- All eight recomputed ratios match saved outputs with maximum absolute error
  **0**. M-score maximum error is **8.881784197001252e-16**; the explicitly
  legacy logistic score's error is **2.220446049250313e-16**. All **15 flags**
  match. Declared absolute tolerance is **1e-10**, relative tolerance **0**.
- Source files and code retain their content/mtime fingerprints across the
  audit. Unit declarations are missing and remain unverified in every target.

The public receipt contains no private source rows, monetary values, local
paths, modification times or row-level predictions. Full local receipts and
run logs remain in the dated private SRG evidence directory. The CLI can rerun
the check against separately authorized source files.

## Quality findings and behavior changes

The full saved extract has **59,507 rows**, including **24,262 observations
with missing M-score but `manipulator_flag=False`** and **42 nonfinite M-scores**.
These are full-extract profile counts, separate from the 15 valid sample targets.
The new implementation leaves invalid scores, flags and logistic outputs as
`None`, reports reasons, and rejects cross-entity pairs, quarter gaps and
declared currency/unit conflicts. It does not repair or overwrite the source.

The original quarterly proxy, simplified TATA, -2.22 rule and sigmoid are
explicitly named legacy conventions. They are not silently replaced by a
standard annual model, and the sigmoid is not labeled fraud probability.

## Executed software validation

Fresh editable installation on macOS arm64/Python 3.12.14:

- **547 tests passed**, including **45 score/proxy tests** and **5 audit-contract
  tests**. The latter detect changed raw inputs, changed saved scores, duplicate
  selected quarters and stable-entity mismatches.
- All **seven CI examples** completed under socket/HTTP network prohibition,
  including the new credential-free Beneish example.
- Ruff passed for the five changed/new Python files; `git diff --check` passed.
- Independent review used a separate rational-arithmetic oracle and confirmed
  that changing saved M-scores does not change newly calculated outputs.

```bash
python -m pytest -q --disable-warnings
python examples/beneish_reproduction_demo.py
python examples/audit_legacy_beneish.py --help
```

The private audit command and field contracts are documented in the definition
reconciliation. Its exact input/code fingerprints and config SHA-256 are in the
aggregate receipt. Hosted Python 3.10/3.11 validation is linked from the PR;
local validation is separate evidence.

## Limits and next decision

Numerical reproduction supports the restored arithmetic, not model suitability
or historical availability. The legacy quarterly formula differs from the
published annual/TTM versions; a standard provider adapter requires a separate
field/basis specification. Adjusted M's generator is still missing, and the
report's fixed five-factor composite does not match recovered dynamic
full-panel implementations. No regression/composite or return-alpha experiment
was performed, and the existing historical-research input gates remain in force.
