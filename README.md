# Systematic Alpha Lab

**Starpoint Research Group · Financial data and systematic research toolkit**

A Python research toolkit for financial data preparation, cross-sectional factor diagnostics, and signal combination.

**Status:** implemented research components with a credential-free synthetic example. Portfolio construction, a standalone risk model, portfolio backtesting, and research agents remain planned modules.

## Start Here

```bash
python -m pip install -e ".[dev]"
python examples/consolidated_import_demo.py
python examples/synthetic_equity_alpha_demo.py
pytest
```

The synthetic example runs:

```text
Synthetic equity prices
  -> momentum / reversal / low-volatility factors
  -> cross-sectional cleaning
  -> factor diagnostics
  -> combined signal
  -> IC / IR / rank-turnover / decay diagnostics
```

The generated data includes a deliberately embedded weak momentum effect. These results demonstrate the software workflow; they are not market evidence or a validated investment strategy. Tests cover imports, synthetic outputs, forward-label timing, future-price invariance of the example factors, and as-of filing selection. They do not establish comprehensive correctness of every weighting engine.

[![Research contracts](https://github.com/SRG-eddieliu/systematic-alpha-lab/actions/workflows/tests.yml/badge.svg)](https://github.com/SRG-eddieliu/systematic-alpha-lab/actions/workflows/tests.yml)

## Focused Research Follow-up

[Integrity research method v1](docs/integrity-research-method-v1.md) defines the
new annual, cash-flow/raw-ratio Beneish specification, required financial fields,
candidate Alpha Vantage mappings and acceptance gates. Accrual quality and Benford
remain separate outputs. Run `python examples/verify_integrity_method_contract.py`
for the public author-fixture arithmetic check. The [annual calculator and pinned
source bridge](docs/annual-beneish-calculator.md) add strict input validation;
`python examples/annual_beneish_demo.py` runs the author-amount example with
explicitly synthetic metadata. Real-source acceptance and empirical validation
remain pending; historical Adjusted M/fixed-five recovery is no longer
a prerequisite for this fresh-data research direction.

The [fresh-data field audit](docs/beneish-field-gaps-2026-10-22.md) adds a reusable
aggregate coverage check and an executed notebook for a fixed 397-task prefix.
The [source-feasibility follow-up](docs/beneish-source-feasibility.md) audits all
1,394 succeeded tasks after collection ended, with 115 failures retained in the
coverage account. AV documents pure depreciation, but the audited source has no
usable values; noncurrent debt and IBEI also remain blocked. Exact S&P 500
membership, accounting equivalence and metadata acceptance remain unverified.

[Financial quality: data gate and protocol](docs/financial-quality-study.md) locks
one sub-study of the wider Integrity Factor review to accrual intensity and
one-month returns. A tested release-time
selector is implemented; actual market evaluation is pending verified publication
timestamps, historical eligibility and suitable return data. No alpha result is
claimed from the current extracts.

The [source consolidation](docs/financial-quality-intake-2026-10-18.md) includes
a tested quarterly accrual diagnostic with fiscal-year cash-flow resets and an
[offline example](examples/financial_quality_snapshot_demo.py). It operates on
one snapshot and does not establish historical tradability. This is a research
module within the platform; each signal study does not imply a separate product.

[Benford diagnostics](docs/benford-diagnostics.md) now have corrected significant-digit
arithmetic, coverage counts and an explicit field-version as-of reference. The old
automatic fiscal-period-to-daily methods raise a migration error because they do
not establish publication timing. No fraud probability or market result is claimed.

[Integrity definition reconciliation](docs/integrity-definition-reconciliation.md)
now separates recovered report definitions from the original notebook behavior.
The [Beneish arithmetic slice](src/systematic_alpha_lab/factor_research/beneish.py)
checks the eight-ratio coefficients against the author's public example and
reproduces an explicitly labeled legacy quarterly proxy with missing/finite,
company and period guards. Run `python examples/beneish_reproduction_demo.py`
without credentials. This is arithmetic restoration, not an annual-model adapter,
fraud probability or validated market signal. The
[definition-gap audit](docs/integrity-definition-gaps-2026-10-22.md) locates the
report's signed five-factor recipe and Adjusted M1 selection. The
[history follow-up](docs/integrity-source-history-2026-10-22.md) also recovers a
separate fixed-five, whole-panel MinMax branch and verifies its normalized
export against known inputs. This differs from both the report's signs and
the sixteen-factor output. Adjusted M generation and the upstream input chain
remain unresolved; the recovered branch has its own explicit execution contract.

## Implemented Components

The [shared snapshot pipeline](docs/data-snapshot-pipeline.md) adds bounded
fundamental-statement collection, immutable JSON observations, a SQLite catalog,
versioned Parquet staging and offline replay. Retrieval time is separate from
historical availability; staged reports are not certified market-factor inputs.

The [offline data reader](docs/offline-data-access.md) provides one read-only
entrypoint for exact existing captures and normalized tables. It exposes source
identity, hashes, coverage and missingness without fetching data, replacing
snapshots or silently selecting the latest version. See the
[Integrity Factor data coverage map](docs/integrity-factor-data-coverage.md) for
the implemented definitions and remaining source requirements before recomputation.

The [provider-only review](docs/provider-statement-review.md) uses those statement
captures directly for annual candidate arithmetic and annual/quarterly source
reconciliation. It needs no additional provider and has an offline synthetic demo.
Its [quarterly TTM path](docs/provider-quarterly-review.md) now connects those
captures to financial-quality arithmetic with explicit source assumptions,
continuity checks and cross-statement difference flags.

The [SEC connector](docs/sec-filing-snapshots.md) adds explicit CIK collection,
accession/context staging, unit and duration preservation, and source-bound replay.
Its synthetic workflow is verified; live statement reconciliation remains pending.

| Component | Code | Scope |
| --- | --- | --- |
| Data preparation | [data_pipeline](src/systematic_alpha_lab/data_pipeline) | Ingestion, transformation, quality checks, and Parquet data access |
| Factor research | [factor_research](src/systematic_alpha_lab/factor_research) | Factor definitions, cross-sectional cleaning, IC/IR, decile and long-short diagnostics |
| Signal combination | [alpha](src/systematic_alpha_lab/alpha) | Signal residualization, composite weighting, evaluation, and experimental ML weighting |
| Research workflow | [workflows](src/systematic_alpha_lab/workflows) | Small synthetic example returning typed research artifacts |
| Shared outputs | [core](src/systematic_alpha_lab/core) | Data, factor, and alpha result dataclasses |

Live-data workflows require the relevant data access, local credentials, and input artifacts. The synthetic workflow does not require those credentials.

## Evaluation Boundaries

- Point-in-time validity must be checked against actual release dates, historical constituents, and the specific data source. A pipeline or date field alone does not establish a leakage-free backtest.
- IC, decile spreads, and long-short diagnostics are research measurements, not a complete tradable portfolio backtest with costs, execution, and constraints.
- `turnover` in the alpha diagnostics is a rank-change proxy, not executed portfolio turnover.
- The current GMV/MVO helpers use transformations of unconstrained weights. They are not general constrained optimizers; normalization also cancels the positive scalar risk-aversion setting in the current MVO helper.
- Real-data results require separate validation of timing, selection, out-of-sample performance, and implementation assumptions.

See the [roadmap](docs/roadmap.md) for the validation work that precedes additional platform features.

## Planned Components

The following directories currently contain placeholders, not completed functionality:

| Component | Package |
| --- | --- |
| Constrained portfolio construction | `portfolio` |
| Standalone risk model | `risk` |
| Portfolio backtesting and attribution | `backtest` |
| Research agents | `agents` |
| Research reporting | `reporting` |

## Configuration

- Data defaults: [config/datalist.yml](config/datalist.yml)
- Factor settings: [config/factors/config.json](config/factors/config.json)
- Alpha settings: [config/alpha/config.json](config/alpha/config.json)
- Default external data root: `../data`

For live ingestion, provide local credentials in `config/credentials.yml` or `config/credential.yml`. Do not commit credentials or redistribute source data without the relevant rights.

## Documentation

- [Shared universe, bounded statement collection and pinned offline replay](docs/shared-pipeline-collection.md)
- [Statement failure diagnosis and offline currency quarantine](docs/statement-failure-recovery.md)
- [Factor diagnostic arithmetic, missingness and coverage](docs/factor-analytics.md)
- [Weighting and monthly study-split contracts](docs/research-correctness-contracts.md)
- [Monthly adjusted-price snapshots and one-month change diagnostics](docs/monthly-price-snapshots.md)
- [SEC quarterly and TTM snapshot diagnostics](docs/sec-quarterly-review.md)
- [Multi-company financial statement diagnostics and pinned replay](docs/provider-batch-review.md)
- [Architecture](docs/architecture.md)
- [Research workflow and APIs](docs/research_workflow.md)
- [Roadmap](docs/roadmap.md)

## Earlier Standalone Repositories

The corresponding implementations are consolidated here. Earlier repositories remain available as development history; this is the starting point for new exploration.

[Source-coverage check](docs/legacy-migration.md): all 83 legacy Python modules
have consolidated counterparts; historical notebooks and Git history remain
available in the original repositories.

| Earlier repository | Consolidated package |
| --- | --- |
| [Data ingestion](https://github.com/SRG-eddieliu/quantlab_step1_data_ingestion) | `systematic_alpha_lab.data_pipeline` |
| [Factor research](https://github.com/SRG-eddieliu/quantlab_step2_factor_research) | `systematic_alpha_lab.factor_research` |
| [Alpha library](https://github.com/SRG-eddieliu/quantlab_step3_alpha_library) | `systematic_alpha_lab.alpha` |


## Control availability policy

The alpha pipeline requires beta and size DataFrames indexed by their **availability timestamps**. Index values must be unique and non-null. Missing dates never fall back to the final row. `control_max_age_days` defaults to `0`, requiring an exact timestamp; a positive value explicitly permits the latest prior row within that many calendar days. Missing history or a stale row raises `ValueError` instead of silently changing the information set. This policy applies to return, thematic-factor and raw-factor purification.

For example, `"control_max_age_days": 3` permits a Friday observation on Monday at matching clock time. The provider must establish when each observation was available; labeling an economic period end as an availability time does not make it point-in-time safe. Existing missing feature values still follow the purification coverage policy. This correction does not validate all upstream data or every weighting/model path.

Regression checks include sparse control histories, bounded staleness, invalid/duplicate timestamps and an end-to-end future-control mutation test for both beta and size.
