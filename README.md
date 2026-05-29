# QuantLab: AI-Assisted Systematic Research Platform

Status: active flagship project, currently being consolidated from modular step repos into a single systematic research platform.

QuantLab is an AI-assisted systematic investing research platform that connects data ingestion, feature engineering, signal generation, factor evaluation, portfolio construction, risk management, backtesting, attribution, and research memo generation. The current implementation is organized as modular repos while the public-facing project is being consolidated into one flagship repository.

## Public Positioning
- **Primary identity**: systematic alpha research and portfolio construction infrastructure.
- **Research scope**: systematic equities first, with room for multi-asset allocation and volatility overlays.
- **AI layer**: agents for hypothesis generation, experiment orchestration, evaluation, and research memo drafting.
- **Public status**: in progress; data, factor, and alpha layers are implemented, while portfolio/risk/backtest layers are planned.

## Module map
- **Step 0: Platform intro & environment** – active landing page, roadmap, environment reproducibility.
- **Step 1: Data ingestion** – implemented ETL for prices, fundamentals, alternative data, lagging/QC, and parquet outputs.
- **Step 2: Factor research** – implemented cross-sectional cleaning, IC/IR, deciles, LS PnL, FF regressions, and coverage diagnostics.
- **Step 3: Alpha library** – implemented purified composites/raws, weighting engines, and regularized walk-forward ML pod.
- **Step 4: Risk engine** – planned/TBD risk model, exposures, limits, and risk budgeting.
- **Step 5: Portfolio optimizer** – planned/TBD RP/MVO/BL with transaction-cost, turnover, and liquidity constraints.
- **Step 6: Backtest engine** – planned/TBD vectorized/event-driven backtests with slippage, costs, and attribution.

Core philosophy: modular (swap/test each step), reproducible (locked env, versioned artifacts), realistic (look-ahead guards, slippage/TC-aware).

## System outline
- **Data pipeline (done)**: ingest raw prices/fundamentals via API, QC/lag, and store parquet in `data/data-processed`. Strict time alignment to avoid look-ahead, especially for event-driven fundamentals/revisions. Includes an MCP-based Alpha Vantage client alongside the REST implementation for flexible integration/testing.
- **Factor library (done)**: compute ~50 equity factors (momentum, value, quality, growth, liquidity, size, forensic, analyst). Per-date cross-sectional cleaning: coverage filter, winsorize, median fill, sector-neutralize, z-score; drop all-NaN dates. Diagnostics: IC/IR, decile spreads, LS PnL, FF regression, rolling IC, coverage stats, plus lightweight long/short portfolio construction to test factor performance. Built on an abstract `FactorBase` interface (`compute_raw_factor` + `post_process`) so new factors plug in cleanly, enforce a consistent contract, improve testability, and keep the runner decoupled from factor internals. Outputs: `data/factors/factor_<name>.parquet` and `diagnostics/factor_analytics_summary.*`.
- **Composites (done)**: thematic blends (value, quality, momentum, reversal, growth accel, forensic, liquidity, systematic risk, size). Config-driven signs/weights; sum available inputs per cell (ignore missing) with optional ffill/zero-fill for sparse forensic. Diagnostics: `composite_analytics_summary.*`, correlations.
- **Alpha compositor (done)**: build alphas from purified composites/raws. Purge returns/factors per date vs sector dummies + beta + size + FF (ridge). Weighting: equal, walk-forward IC, rolling ridge MLR (skip ill-conditioned), Bayesian shrink, rolling GMV/MVO, ML pod (XGB/RF/GBM/MLP) walk-forward. Outputs alphas to `data/alpha/` and metrics to `diagnostics/alpha_metrics_all.csv`.
- **Portfolio & risk (next)**: add multi-sleeve risk/turnover/liquidity constraints, exposure controls, and optimizers (RP/MVO/BL). Transaction-cost modeling and risk model are upcoming.

## Key procedures & considerations
- **No look-ahead**: lag fundamentals/events, forward-shift returns; walk-forward windows for IC/MLR/ML; rolling cov for GMV/MVO.
- **Cross-sectional first**: factor cleaning, IC/IR, purge regressions, and weighting are per-date across names. Time-series used for rolling analytics/train windows.
- **Purification**: per-date ridge regression to strip sector/beta/size/FF effects from returns and factors; residuals feed weighting/ML.
- **Sparse signals**: keep event factors sparse (NaN = no event); composites ignore missing inputs; forensic composite ffill+zero-fill to stay usable in ML.
- **Coverage stats**: diagnostics include dq_* fields (non-null %, coverage by date), dropping permanently empty tickers/dates.
- **ML caution**: ML pod treated as additive; regularize heavily, shorten train/val for speed, and skip weak models if IC ~ 0. XGBoost requires `xgboost`/`libomp`.

## Demo flow
1) **Factor build/diagnostics** (quantlab_factor_library):
   - Run `notebooks/factor_parallel_demo.ipynb`.
   - Inspect `diagnostics/factor_analytics_summary.csv` and `composite_analytics_summary.csv`.
2) **Alpha build** (quantlab_alpha_compositor):
   - Run `notebooks/alpha_demo.ipynb` with refreshed factors.
   - Check `diagnostics/alpha_metrics_all.csv` and sample `data/alpha/alpha_*.parquet`.
3) **(Next) Portfolio**:
   - Feed alphas + risk model into optimizer; add constraints by sleeve (core/systematic, event/info, growth/cyclical, ML-neutral).

## Environments
- Base deps captured in `environment.yml` (Python ≥3.10, pandas/numpy/sklearn, optional xgboost). Install via `conda env create -f environment.yml` then `conda activate quantlab`.

## Repos (sibling)
- `quantlab_data_pipeline_api`: data ingest/QC, parquet outputs under `data/data-processed`.
- `quantlab_factor_library`: factor computation, cleaning, diagnostics, composites, saved factors under `data/factors`.
- `quantlab_alpha_compositor`: purification, weighting/ML, alpha outputs under `data/alpha`.

## Notes for portfolio use
- Use purified alphas; add exposure, sector, turnover, liquidity limits; model costs.
- Weak ML signals: consider shorter windows/fewer methods or drop until tuned.
- Coverage varies by theme; composites handle missing inputs automatically; forensic/growth accel are sparser by design.
