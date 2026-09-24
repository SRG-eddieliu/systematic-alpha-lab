# Roadmap

## Current Scope

Data preparation, factor research, and signal combination are consolidated under `src/systematic_alpha_lab/`. A synthetic workflow demonstrates their interaction without external credentials.

Existing tests cover imports and basic output structure. They do not establish investment performance or comprehensive numerical correctness.

## Priority 1: Research Correctness

1. Add tests for forward-return alignment, missing-data handling, and signal timing.
2. Verify fundamental release dates and historical universe membership before making point-in-time claims.
3. Add numerical checks for factor analytics and weighting helpers.
4. Replace or explicitly separate the GMV/MVO heuristics from constrained portfolio optimization. Test that any risk-aversion parameter has its intended effect.
5. Document train/validation/test boundaries for real-data experiments and keep selection separate from final evaluation.

## Priority 2: Reproducible Examples

1. Expand the synthetic smoke tests with numerical expectations and edge cases.
2. Record dependency versions, configuration, and random seeds.
3. Add a small lawful data example and a research memo describing its assumptions and limitations.
4. Keep live-data setup separate from credential-free demonstrations.

## Future Features

The following are planned, not delivered:

- Standalone risk exposures and covariance estimation.
- Constrained portfolio construction with turnover and liquidity limits.
- Portfolio backtesting, execution costs, and attribution.
- Research reporting and optional agent-assisted experiment workflows.

Correctness and reproducibility take priority over adding these layers.

## Repository Organization

Use this repository for the consolidated implementation. The three earlier `quantlab_step*` repositories retain standalone development history; their documentation may describe older paths and assumptions.
