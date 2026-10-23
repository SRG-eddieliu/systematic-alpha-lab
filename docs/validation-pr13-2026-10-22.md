# Offline reader review and validation — 2026-10-22

This review started from PR 13 head
`b18d6e76205f5c81baf2521fbb6d05248ff7f26e`. Validation ran in a fresh
editable installation on macOS arm64, Python 3.12.14. Existing Python 3.10/3.11
hosted checks are separate evidence; the updated head must pass them again.

## Review finding and repair

Known annual, quarterly and batch review contracts embed complete registered
source manifests. An ID-only dependency could previously bypass manifest
recursion, which recognizes a manifest by `snapshot_id`, `normalizer` and
`tables`. A synthetic quarterly review with a corrupt cash-flow source was
incorrectly accepted after its annual dependency was truncated and its derived
version suffix recomputed: eight output rows were returned, but only one of
three sources was verified.

The reader now requires complete embedded-manifest structure at each known
review boundary. Existing recursion then verifies exact catalog equality and
every declared source. Four new regressions cover annual, provider quarterly,
SEC quarterly and batch reviews; all four failed on the original head and pass
after the repair. This verifies a declared derivation contract, not external
authentication of a catalog.

## Executed validation

- Original head: **493 tests passed**.
- Repaired source: **497 tests passed**; reader suite: **37 passed**.
- Ruff passed for the reader and its tests; `git diff --check` passed.
- All six CI example commands passed under a socket/HTTP network prohibition.
- An existing private Alpha Vantage catalog was read through `catalog/read`:
  **14 registered tables**, **684 table rows**. All **18 input files** retained
  their exact content hashes and modification times; **zero network attempts**.
  These are counts of registered tables/rows, not unique financial observations.
- Every result retained `readiness.status = "not_certified"`.

Commands from the installed repository:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q --disable-warnings
ruff check src/systematic_alpha_lab/data_pipeline/offline_reader.py tests/test_offline_reader.py
python examples/consolidated_import_demo.py
python examples/av_batch_review_demo.py
python examples/sec_quarterly_review_demo.py
python examples/monthly_price_snapshot_demo.py
python examples/offline_data_access_demo.py
python examples/research_contracts_demo.py
```

Observed packages: NumPy 2.5.4, pandas 2.2.3, PyArrow 26.0.0, SciPy 1.18.1,
scikit-learn 1.9.1, pytest 9.1.1, Ruff 0.17.2. The suite emits existing
NumPy/pandas timedelta deprecation warnings; they did not fail these checks.

Validated source SHA-256:

- `offline_reader.py`: `86cf1c6b21c8b0f79c3cc71a0b9a4e7f0b10e4063e410bd0fb073f0b02664380`
- `test_offline_reader.py`: `53b022c14c91decf063d0a74a5be353906d7f9aad6f8e5766f8a19d342968ad4`

Full local logs, synthetic pre/post reproductions and private input fingerprints
are retained in the dated SRG evidence directory. This public record includes
no private source rows, credentials or raw financial responses. The reader
continues to require a quiescent catalog and does not establish financial
definition correctness, historical availability or investment performance.
