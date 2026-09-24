# Systematic Alpha Lab

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

The generated data includes a deliberately embedded weak momentum effect. These results demonstrate the software workflow; they are not market evidence or a validated investment strategy. Existing tests cover imports and basic synthetic workflow outputs, not comprehensive numerical or temporal correctness.

## Implemented Components

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

- [Architecture](docs/architecture.md)
- [Research workflow and APIs](docs/research_workflow.md)
- [Roadmap](docs/roadmap.md)

## Earlier Standalone Repositories

The corresponding implementations are consolidated here. Earlier repositories remain available as development history; this is the starting point for new exploration.

| Earlier repository | Consolidated package |
| --- | --- |
| [Data ingestion](https://github.com/SRG-eddieliu/quantlab_step1_data_ingestion) | `systematic_alpha_lab.data_pipeline` |
| [Factor research](https://github.com/SRG-eddieliu/quantlab_step2_factor_research) | `systematic_alpha_lab.factor_research` |
| [Alpha library](https://github.com/SRG-eddieliu/quantlab_step3_alpha_library) | `systematic_alpha_lab.alpha` |
