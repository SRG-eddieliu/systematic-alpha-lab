# Roadmap

## Current Scope

Data preparation, factor research, and signal combination are consolidated under `src/systematic_alpha_lab/`. A synthetic workflow demonstrates their interaction without external credentials.

Existing tests cover imports and basic output structure. They do not establish investment performance or comprehensive numerical correctness.

## Priority 1: Research Correctness

1. Add tests for forward-return alignment, missing-data handling, and signal timing.
2. Verify fundamental release dates and historical universe membership before making point-in-time claims.
3. Expand numerical checks for factor analytics and weighting helpers. The
   [diagnostic arithmetic repair](factor-analytics.md) covers signed bucket
   spreads, formation-only assignment, missing selected returns, coverage and
   the initial wealth baseline. The [weighting contract](research-correctness-contracts.md)
   adds covariance-label alignment, finite/PSD checks and hand-calculated
   coefficient cases. This is not exhaustive numerical certification.
4. The [explicit covariance-direction APIs](research-correctness-contracts.md)
   separate the legacy GMV/MVO heuristics from constrained portfolio optimization.
   Tests verify that positive legacy risk scaling cancels under unit-gross
   normalization; a genuine constrained optimizer remains a future component.
5. The [monthly split reference](research-correctness-contracts.md) implements
   predeclared 60/20/20 month boundaries and purges unavailable labels. Freeze
   actual input hashes and calendar boundaries after the real-data gate passes;
   keep model selection separate from final evaluation.

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
