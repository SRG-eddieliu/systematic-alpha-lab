from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class DataBundle:
    """In-memory research dataset shared across workflow stages."""

    prices: pd.DataFrame
    returns_forward: pd.DataFrame
    sectors: pd.Series | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FactorResearchResult:
    """Output of a factor research workflow."""

    factors: dict[str, pd.DataFrame]
    analytics: dict[str, dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AlphaResearchResult:
    """Output of an alpha construction/evaluation workflow."""

    alpha: pd.DataFrame
    metrics: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
