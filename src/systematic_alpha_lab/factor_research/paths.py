from __future__ import annotations

import json
from pathlib import Path
from functools import lru_cache


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _load_config() -> dict:
    cfg_path = repo_root() / "config" / "factors" / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text())
        except Exception:
            return {}
    return {}


def _resolve_path(val: str) -> Path:
    path = Path(val).expanduser()
    if not path.is_absolute():
        path = repo_root() / path
    return path.resolve()


def data_root() -> Path:
    cfg = _load_config()
    if "data_root" in cfg:
        return _resolve_path(cfg["data_root"])
    return repo_root().parent / "data"


def factors_dir() -> Path:
    cfg = _load_config()
    if "factors_dir" in cfg:
        return _resolve_path(cfg["factors_dir"])
    return data_root() / "factors"


def final_data_dir() -> Path:
    # Cleaned long-format outputs from the previous pipeline
    cfg = _load_config()
    if "final_dir" in cfg:
        return _resolve_path(cfg["final_dir"])
    return data_root() / "data-processed"
