# Architecture

Systematic Alpha Lab is organized as a modular research platform. The current consolidated codebase keeps implemented layers independent while making them importable from one package.

```text
Data Pipeline
    -> Factor Research
    -> Alpha Construction
    -> Risk Model
    -> Portfolio Construction
    -> Backtest and Attribution
    -> Research Reporting
```

## Implemented Layers

| Layer | Package | Role |
| --- | --- | --- |
| Workflows | `systematic_alpha_lab.workflows` | Runnable end-to-end workflows that hide lower-level complexity |
| Core Artifacts | `systematic_alpha_lab.core` | Shared dataclasses for data, factor, and alpha research outputs |
| Data Pipeline | `systematic_alpha_lab.data_pipeline` | Ingest, transform, quality-check, and serve market/fundamental/macro data |
| Factor Research | `systematic_alpha_lab.factor_research` | Build equity factors, clean cross-sections, evaluate IC/IR, and create thematic composites |
| Alpha Construction | `systematic_alpha_lab.alpha` | Purify signals, combine themes, evaluate alphas, and run walk-forward weighting/ML experiments |

## Planned Layers

| Layer | Package | Status |
| --- | --- | --- |
| Risk Model | `systematic_alpha_lab.risk` | Placeholder |
| Portfolio Construction | `systematic_alpha_lab.portfolio` | Placeholder |
| Backtest and Attribution | `systematic_alpha_lab.backtest` | Placeholder |
| Agentic Research | `systematic_alpha_lab.agents` | Placeholder |
| Reporting | `systematic_alpha_lab.reporting` | Placeholder |

## Configuration

- Data ingestion defaults: `config/datalist.yml`
- Factor cleaning/composite config: `config/factors/config.json`
- Alpha construction config: `config/alpha/config.json`

Credentials are intentionally not committed. Put local credentials in `config/credentials.yml` or `config/credential.yml`.
