from __future__ import annotations

import logging
from typing import Dict, List

import pandas as pd

from .paths import final_dataset_path, final_dir

logger = logging.getLogger(__name__)


def _missing_detail(df: pd.DataFrame, top_n: int = 10) -> List[str]:
    total = len(df)
    if total == 0:
        return []
    na_counts = df.isna().sum()
    nonzero = na_counts[na_counts > 0].sort_values(ascending=False)
    details = []
    for col, cnt in nonzero.head(top_n).items():
        pct = (cnt / total) * 100 if total else 0
        details.append(f"{col}: {int(cnt)} ({pct:.3f}%)")
    return details


def _load_dataset(name: str) -> pd.DataFrame:
    return pd.read_parquet(final_dataset_path(name))


def run_quality_checks(dataset: str = "price_daily", top_missing: int = 10) -> Dict[str, Dict[str, List[str]]]:
    """
    Quality checks on final datasets.

    - If `dataset` is a specific name (e.g., price_daily), runs checks on that dataset.
    - If `dataset` == "all", scans every parquet in the final dir.
    Returns a dict keyed by dataset with lists for missing/consistency/bounds/missing_detail.
    """
    datasets: List[str]
    if dataset == "all":
        datasets = sorted([p.stem for p in final_dir().glob("*.parquet")])
    else:
        datasets = [dataset]

    reports: Dict[str, Dict[str, List[str]]] = {}
    for ds in datasets:
        try:
            df = _load_dataset(ds)
        except FileNotFoundError:
            logger.warning("Dataset %s not found in final_dir", ds)
            continue
        issues: Dict[str, List[str]] = {"missing": [], "consistency": [], "bounds": [], "missing_detail": []}

        # Common: missing values
        if df.isna().any().any():
            issues["missing"].append(f"Rows with any missing values: {int(df.isna().any(axis=1).sum())}")
            issues["missing_detail"] = _missing_detail(df, top_missing)

        # Price-specific consistency/bounds
        required_cols = {"open", "high", "low", "close"}
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        if required_cols.issubset(df.columns):
            bad_open_high = df[df["open"] > df["high"]]
            bad_low_close = df[df["low"] > df["close"]]
            if not bad_open_high.empty:
                issues["consistency"].append(f"open>high rows: {len(bad_open_high)}")
            if not bad_low_close.empty:
                issues["consistency"].append(f"low>close rows: {len(bad_low_close)}")
        if "volume" in df.columns:
            negative = df[df["volume"] < 0]
            if not negative.empty:
                issues["bounds"].append(f"Negative volume values: {len(negative)} rows")

        reports[ds] = issues

    # Log a summary
    for ds, issues in reports.items():
        if not any(issues.values()):
            logger.info("Quality checks passed for %s with no issues detected.", ds)
        else:
            logger.warning("Quality checks for %s found issues: %s", ds, issues)

    return reports
