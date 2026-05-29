from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return repository root inferred from this file location."""
    return Path(__file__).resolve().parents[3]


def data_root() -> Path:
    """
    Return external data root (sibling to repo), e.g., quant-lab/data/.
    Defaults to ../data relative to repo root.
    """
    return repo_root().parent / "data"


def raw_data_dir() -> Path:
    """Landing zone for raw parquet outputs."""
    return data_root() / "data-raw"


def final_data_path() -> Path:
    """Default final dataset path (price daily)."""
    return data_root() / "data-processed" / "price_daily.parquet"


def final_dir() -> Path:
    """Directory for final datasets."""
    return data_root() / "data-processed"


def final_dataset_path(name: str) -> Path:
    """Path helper for named final datasets (e.g., price_daily, price_weekly)."""
    return final_dir() / f"{name}.parquet"
