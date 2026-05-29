# Systematic Alpha Lab

AI-assisted systematic alpha research platform for factor research, signal generation, alpha evaluation, portfolio construction, and research automation.

Status: active flagship project. The implemented data, factor research, and alpha construction modules have been consolidated into this repository under `src/systematic_alpha_lab/`. The older step repos remain useful implementation history, but this repo is now the public center of gravity.

## Research Workflow

```text
Data Ingestion
    -> Feature Engineering
    -> Signal Generation
    -> Factor Evaluation
    -> Alpha Construction
    -> Portfolio Construction
    -> Risk Management
    -> Backtesting and Attribution
    -> Research Memo Generation
```

## Implemented Platform Layers

| Layer | Package | Status | Purpose |
| --- | --- | --- | --- |
| Data Pipeline | `systematic_alpha_lab.data_pipeline` | Implemented | Ingest, transform, quality-check, and serve price/fundamental/macro datasets |
| Factor Research | `systematic_alpha_lab.factor_research` | Implemented | Build cross-sectional equity factors, clean signals, run IC/IR and decile diagnostics |
| Alpha Construction | `systematic_alpha_lab.alpha` | Implemented | Purify signals, combine thematic composites, evaluate alphas, run walk-forward weighting/ML experiments |
| Portfolio Construction | `systematic_alpha_lab.portfolio` | Planned | Turn alphas into constrained weights |
| Risk Model | `systematic_alpha_lab.risk` | Planned | Estimate exposures, covariance, limits, and risk budgets |
| Backtest / Attribution | `systematic_alpha_lab.backtest` | Planned | Evaluate portfolio returns, costs, turnover, drawdown, and attribution |
| Agentic Research | `systematic_alpha_lab.agents` | Planned | Generate hypotheses, run experiments, evaluate outputs, and draft research memos |

## What This Demonstrates

- Point-in-time data handling for market, fundamental, macro, and benchmark inputs.
- Cross-sectional factor engineering across momentum, value, quality, growth, liquidity, risk, size, forensic, and analyst themes.
- Factor diagnostics: rank IC, IC IR, decile spreads, long-short PnL, Fama-French regression, coverage stats, and rolling analytics.
- Alpha construction with purification against sector, beta, size, and style controls.
- Walk-forward weighting engines: equal weight, IC weighting, MLR, Bayesian shrinkage, GMV/MVO, and regularized ML pods.
- A path toward AI-assisted systematic research: hypothesis agent, experiment runner, evaluation agent, and report generator.

## Repository Layout

```text
systematic-alpha-lab/
  src/systematic_alpha_lab/
    data_pipeline/       # data ingestion, transformation, quality checks
    factor_research/     # factor library, cleaning, diagnostics, composites
    alpha/               # alpha purification, weighting, evaluation
    portfolio/           # planned
    risk/                # planned
    backtest/            # planned
    agents/              # planned
    reporting/           # planned
  config/
    datalist.yml
    factors/config.json
    alpha/config.json
  docs/
    architecture.md
    roadmap.md
  examples/
  tests/
```

## Quickstart

Install in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Run the lightweight import check:

```bash
python examples/consolidated_import_demo.py
pytest
```

Credentials are not committed. For live ingestion, create `config/credentials.yml` or `config/credential.yml` locally with Alpha Vantage and WRDS credentials.

## Configuration

- Data defaults: `config/datalist.yml`
- Factor cleaning and composite definitions: `config/factors/config.json`
- Alpha construction and model settings: `config/alpha/config.json`
- Default data root: `../data`, matching the existing local research artifact layout.

## Legacy Component Repos

These repos are being consolidated into this flagship codebase:

| Legacy repo | Consolidated package |
| --- | --- |
| `quantlab_step1_data_ingestion` | `systematic_alpha_lab.data_pipeline` |
| `quantlab_step2_factor_research` | `systematic_alpha_lab.factor_research` |
| `quantlab_step3_alpha_library` | `systematic_alpha_lab.alpha` |

## Documentation

- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
