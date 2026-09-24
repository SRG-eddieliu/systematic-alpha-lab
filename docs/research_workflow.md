# Research Workflow

This project has two levels of API.

## Simple API

Use this when you want to understand or demo the platform quickly.

```python
from systematic_alpha_lab.workflows import run_synthetic_equity_alpha_demo

data, factor_result, alpha_result = run_synthetic_equity_alpha_demo()
```

This runs a credential-free synthetic demonstration of the implemented research components:

```text
Synthetic prices
    -> Momentum / reversal / low-vol factors
    -> Factor cleaning
    -> Factor IC and long-short diagnostics
    -> Combined alpha score
    -> Alpha IC / IR / turnover / decay
```

The data generator deliberately embeds a weak momentum effect. Metrics from this demonstration are not evidence of real-market alpha. Portfolio construction, trading costs, risk modeling, and portfolio backtesting are outside this example.

The result objects are typed dataclasses:

- `DataBundle`
- `FactorResearchResult`
- `AlphaResearchResult`

## Advanced API

Use these lower-level components for configured live-data research. They require separate data-quality, timing, and numerical validation before drawing investment conclusions.

```python
from systematic_alpha_lab.data_pipeline import run_ingestion, transform_raw_to_final
from systematic_alpha_lab.factor_research.run_factors import compute_factors, run_analytics_only
from systematic_alpha_lab.alpha import run_alpha_pipeline
```

Advanced flow:

```text
WRDS + Alpha Vantage
    -> raw parquet
    -> processed parquet
    -> factor parquet
    -> alpha parquet
```

The advanced API requires local credentials and data artifacts. The simple synthetic workflow does not.

## Naming Guide

Some original modules remain for backward compatibility. Prefer these clearer names when writing new code:

| Prefer | Backward-compatible module |
| --- | --- |
| `data_pipeline.raw_to_processed` | `data_pipeline.transform` |
| `factor_research.factor_cleaning` | `factor_research.transforms` |
| `alpha.alpha_preprocessing` | `alpha.preprocess` |
| `alpha.alpha_engine` | `alpha.pipeline` |
