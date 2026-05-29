from __future__ import annotations

import logging
from io import StringIO
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageRESTClient:
    """Minimal REST client for Alpha Vantage CSV endpoints."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def fetch_json(self, function: str, params: Optional[dict] = None) -> dict:
        payload = {"function": function, "apikey": self.api_key}
        if params:
            payload.update(params)
        logger.info("Fetching %s via REST (json)", function)
        resp = self.session.get(BASE_URL, params=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def fetch_time_series_csv(
        self,
        function: str,
        symbol: str,
        outputsize: str = "full",
        adjusted: bool = True,
    ) -> pd.DataFrame:
        params = {
            "function": function,
            "symbol": symbol,
            "apikey": self.api_key,
            "datatype": "csv",
            "outputsize": outputsize,
        }
        if function == "TIME_SERIES_INTRADAY" and not adjusted:
            params["adjusted"] = "false"

        logger.info("Fetching %s via REST for %s", function, symbol)
        resp = self.session.get(BASE_URL, params=params, timeout=60)
        resp.raise_for_status()
        text = resp.text
        df = pd.read_csv(StringIO(text))
        # Normalize column names to lower snake for consistency
        df.columns = [c.strip().lower() for c in df.columns]
        df["symbol"] = symbol
        return df
