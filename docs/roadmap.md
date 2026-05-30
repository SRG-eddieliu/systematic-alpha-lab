# Roadmap

## Current State

- Consolidated parent repo created.
- Data, factor research, and alpha construction modules moved into `src/systematic_alpha_lab/`.
- Existing component repos remain available for history but are no longer the intended public center of gravity.

## Near-Term

1. Expand smoke tests for config resolution and small synthetic factor runs.
2. Extend the synthetic end-to-end demo into a notebook narrative.
3. Add sample research memo output under `reports/examples/`.
4. Convert the current notebooks into parent-repo examples.

## Medium-Term

1. Add risk model: beta, sector, style, idiosyncratic volatility, covariance estimation.
2. Implement portfolio construction: risk parity, mean-variance, constraints, turnover, liquidity.
3. Add backtest and attribution: slippage, costs, turnover, exposures, drawdown, factor attribution.
4. Add agentic research layer: hypothesis, experiment, evaluation, and report agents.

## Public Positioning

The flagship repo should communicate a systematic research platform, not a sequence of course-style steps. The old component repos can remain linked as implementation history until the consolidated repo fully replaces them.
