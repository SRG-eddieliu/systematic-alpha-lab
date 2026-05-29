from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict


def rank_ic(alpha: pd.DataFrame, fwd_ret: pd.DataFrame) -> pd.Series:
    ic = {}
    common_idx = alpha.index.intersection(fwd_ret.index)
    for dt in common_idx:
        a = alpha.loc[dt]
        r = fwd_ret.loc[dt]
        df = pd.concat([a, r], axis=1, keys=["a", "r"]).dropna()
        if len(df) < 5:
            ic[dt] = np.nan
            continue
        # Guard constant-series to avoid ConstantInputWarning
        if df["a"].nunique() <= 1 or df["r"].nunique() <= 1:
            ic[dt] = np.nan
            continue
        ic[dt] = df["a"].rank().corr(df["r"].rank(), method="spearman")
    return pd.Series(ic)


def turnover(alpha: pd.DataFrame) -> float:
    ranks = alpha.rank(axis=1, method="average", pct=True)
    diff = ranks.diff().abs()
    stacked = diff.stack().dropna()
    return stacked.mean() if not stacked.empty else np.nan


def alpha_decay(alpha: pd.DataFrame, fwd_ret: pd.DataFrame, horizons=(5, 10, 21)) -> Dict[int, float]:
    out = {}
    for h in horizons:
        shifted = fwd_ret.shift(-h)
        ic = rank_ic(alpha, shifted)
        out[h] = ic.mean()
    return out


def evaluate_alpha(alpha: pd.DataFrame, fwd_ret: pd.DataFrame) -> dict:
    """
    Compute IC, IR, decay, turnover for an alpha series (wide Date x Ticker).
    """
    ic_series = rank_ic(alpha, fwd_ret)
    ic = ic_series.mean()
    ir = ic_series.mean() / ic_series.std() if ic_series.std() not in (0, np.nan) else np.nan
    return {
        "ic": ic,
        "ir": ir,
        "ic_series": ic_series,
        "decay": alpha_decay(alpha, fwd_ret),
        "turnover": turnover(alpha),
    }
