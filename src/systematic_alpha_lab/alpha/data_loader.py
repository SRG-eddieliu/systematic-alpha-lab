import json
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[3]


def _resolve(pathlike: str | Path) -> Path:
    p = Path(pathlike)
    return p if p.is_absolute() else (BASE_DIR / p).resolve()


def load_config(path: str | Path) -> dict:
    cfg_path = Path(path)
    return json.loads(cfg_path.read_text())


class AlphaDataLoader:
    """
    Thin loader around parquet artifacts produced by the data pipeline and factor library.
    Resolves relative paths against the repo base.
    """

    def __init__(self, config: dict):
        self.cfg = config

    def load_price(self) -> pd.DataFrame:
        df = pd.read_parquet(_resolve(self.cfg["price_file"]))
        df["date"] = pd.to_datetime(df["date"])
        df = df.pivot(index="date", columns="ticker", values="open")
        return df.sort_index()

    def load_volume(self) -> pd.DataFrame:
        df = pd.read_parquet(_resolve(self.cfg["price_file"]))
        df["date"] = pd.to_datetime(df["date"])
        df = df.pivot(index="date", columns="ticker", values="volume")
        return df.sort_index()

    def load_ff(self) -> Optional[pd.DataFrame]:
        ff_path = _resolve(self.cfg["ff_file"])
        if not ff_path.exists():
            return None
        ff = pd.read_parquet(ff_path)
        ff["date"] = pd.to_datetime(ff["date"])
        ff = ff.set_index("date").sort_index()
        return ff

    def load_factor(self, name: str) -> pd.DataFrame:
        path = _resolve(self.cfg["factor_dir"]) / f"factor_{name}.parquet"
        df = pd.read_parquet(path)
        df["Date"] = pd.to_datetime(df["Date"])
        wide = df.pivot(index="Date", columns="Ticker", values="Value").sort_index()
        return wide

    def load_composite(self, name: str) -> pd.DataFrame:
        path = _resolve(self.cfg["factor_dir"]) / f"factor_{name}.parquet"
        df = pd.read_parquet(path)
        df["Date"] = pd.to_datetime(df["Date"])
        wide = df.pivot(index="Date", columns="Ticker", values="Value").sort_index()
        return wide

    def load_many_factors(self, names: list[str]) -> Dict[str, pd.DataFrame]:
        return {n: self.load_factor(n) for n in names}
