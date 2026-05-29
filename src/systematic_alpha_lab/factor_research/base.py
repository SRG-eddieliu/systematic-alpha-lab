from __future__ import annotations

import abc
import json
from functools import lru_cache
from typing import Optional

import pandas as pd

from . import transforms
from .paths import repo_root


@lru_cache(maxsize=1)
def _factor_config() -> dict:
    """
    Load optional factor cleaning config from config/factors/config.json.
    Supports:
      - factor_defaults: winsor_limits (list/tuple), min_coverage, fill_method, neutralize_method
      - factor_overrides: per-factor dict keyed by factor name/class name with same keys as defaults
      - forward_fill (bool) as part of defaults/overrides for factors that support it
    """
    cfg_path = repo_root() / "config" / "factors" / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text()) or {}
    except Exception:
        return {}


def factor_setting(name: str, cls_name: str, key: str, default=None):
    """
    Helper to read a setting (key) from factor_overrides or factor_defaults.
    name: factor instance name (self.name)
    cls_name: class name
    """
    cfg = _factor_config()
    defaults = cfg.get("factor_defaults", {})
    overrides = cfg.get("factor_overrides", {})
    ov = overrides.get(name) or overrides.get(cls_name) or {}
    return ov.get(key, defaults.get(key, default))


class FactorBase(abc.ABC):
    """
    Base class enforcing compute_raw_factor + post_process contract.
    """

    name: str = "factor_base"

    @abc.abstractmethod
    def compute_raw_factor(self, data_loader) -> pd.DataFrame:
        """Return a wide DataFrame (index=date, cols=tickers) of raw factor values."""

    @abc.abstractmethod
    def post_process(self, raw_factor: pd.DataFrame) -> pd.DataFrame:
        """Optional shifting/smoothing specific to the factor."""

    def compute(
        self,
        data_loader,
        sector_map: Optional[pd.Series] = None,
        winsor_limits: Optional[tuple[float, float]] = None,
        min_coverage: Optional[float] = None,
        fill_method: Optional[str] = None,
        neutralize_method: Optional[str] = None,
    ) -> pd.DataFrame:
        raw = self.compute_raw_factor(data_loader)
        post = self.post_process(raw)
        cfg = _factor_config()
        defaults = cfg.get("factor_defaults", {})
        overrides = cfg.get("factor_overrides", {})
        name_key = getattr(self, "name", None) or self.__class__.__name__
        ov = overrides.get(name_key) or overrides.get(self.__class__.__name__)

        wl = (
            winsor_limits
            if winsor_limits is not None
            else tuple((ov or {}).get("winsor_limits", defaults.get("winsor_limits", (0.01, 0.99))))
        )
        mc = (
            min_coverage
            if min_coverage is not None
            else (ov or {}).get("min_coverage", defaults.get("min_coverage", 0.3))
        )
        fm = fill_method if fill_method is not None else (ov or {}).get("fill_method", defaults.get("fill_method", "median"))
        nm = (
            neutralize_method
            if neutralize_method is not None
            else (ov or {}).get("neutralize_method", defaults.get("neutralize_method", "sector"))
        )
        cleaned = transforms.clean_factor(
            post,
            sector_map=sector_map,
            winsor_limits=wl,
            min_coverage=mc,
            fill_method=fm,
            neutralize_method=nm,
        )
        return cleaned
