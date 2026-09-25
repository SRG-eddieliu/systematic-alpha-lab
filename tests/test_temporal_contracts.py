import numpy as np
import pandas as pd

from systematic_alpha_lab.alpha import compute_forward_returns
from systematic_alpha_lab.workflows.synthetic_equity_alpha import (
    make_synthetic_equity_data, build_simple_factors, build_alpha,
)


def test_forward_label_has_explicit_holding_interval():
    prices = pd.DataFrame({"A": [100., 110., 99., 108.9]})
    result = compute_forward_returns(prices, shift=1)
    np.testing.assert_allclose(result.A, [.1, -.1, .1, np.nan], equal_nan=True)


def test_future_prices_cannot_change_past_factors_or_alpha():
    original = make_synthetic_equity_data(n_days=100, n_assets=24, seed=11)
    changed = make_synthetic_equity_data(n_days=100, n_assets=24, seed=11)
    changed.prices.iloc[70:] *= 3
    before, after = build_simple_factors(original), build_simple_factors(changed)
    cutoff = original.prices.index[70]
    for name in before:
        pd.testing.assert_frame_equal(before[name].loc[before[name].index < cutoff],
                                      after[name].loc[after[name].index < cutoff])
    a, b = build_alpha(before), build_alpha(after)
    pd.testing.assert_frame_equal(a.loc[a.index < cutoff], b.loc[b.index < cutoff])


def test_fixed_seed_reproduces_synthetic_prices():
    a = make_synthetic_equity_data(n_days=100, n_assets=24, seed=11)
    b = make_synthetic_equity_data(n_days=100, n_assets=24, seed=11)
    pd.testing.assert_frame_equal(a.prices, b.prices)
