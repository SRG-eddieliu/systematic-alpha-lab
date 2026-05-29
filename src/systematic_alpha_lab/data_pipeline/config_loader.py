from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


def _candidate_paths() -> list[Path]:
    base = Path(__file__).resolve().parents[3]
    return [
        base / "credentials.yml",
        base / "config" / "credentials.yml",
        base / "config" / "credential.yml",
    ]


def load_credentials(path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load credentials from YAML.

    Expected keys:
        - alphavantage_api / alphavantage_api_paid
        - wrds (with username/password) or wrds_username/wrds_password
    """
    if path:
        paths = [path]
    else:
        paths = _candidate_paths()

    for candidate in paths:
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as f:
                raw = f.read()
            data = yaml.safe_load(raw) or {}
            if isinstance(data, str):
                # Fallback for key=value style files.
                parsed: Dict[str, Any] = {}
                for line in raw.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    parsed[key] = val
                data = parsed
            logger.info("Loaded credentials from %s", candidate)
            return data

    raise FileNotFoundError("No credentials YAML found in expected locations.")
