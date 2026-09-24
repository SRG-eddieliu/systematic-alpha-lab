# Architecture

Systematic Alpha Lab groups existing research components into one Python package.

## Implemented Flow

```text
Data preparation -> factor construction and diagnostics -> signal combination and diagnostics
```

The credential-free entry point uses synthetic prices. Live-data workflows use separate credentials and data artifacts.

| Layer | Package | Role |
| --- | --- | --- |
| Workflows | `systematic_alpha_lab.workflows` | Synthetic demonstration connecting the implemented components |
| Core artifacts | `systematic_alpha_lab.core` | Dataclasses for data, factor, and alpha outputs |
| Data pipeline | `systematic_alpha_lab.data_pipeline` | Ingestion, transformation, quality checks, and data access |
| Factor research | `systematic_alpha_lab.factor_research` | Factor definitions, cleaning, diagnostics, and composites |
| Alpha construction | `systematic_alpha_lab.alpha` | Signal residualization, weighting experiments, and evaluation |

The presence of an implementation does not imply that all numerical methods or real-data assumptions have been validated. In particular, the weighting helpers are not a general constrained portfolio optimizer.

## Planned Extensions

```text
Signal diagnostics -> risk model -> constrained portfolio -> portfolio backtest -> reporting
                       planned          planned               planned          planned
```

The `risk`, `portfolio`, `backtest`, `agents`, and `reporting` packages currently contain placeholders.

## Configuration

- Data ingestion: `config/datalist.yml`
- Factor cleaning and composites: `config/factors/config.json`
- Signal combination: `config/alpha/config.json`

Keep local credentials in `config/credentials.yml` or `config/credential.yml`, outside version control. External data access and redistribution remain subject to the source's terms.

See the [workflow guide](research_workflow.md) for entry points and the [roadmap](roadmap.md) for validation priorities.
