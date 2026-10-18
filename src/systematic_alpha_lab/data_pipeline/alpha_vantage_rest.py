from __future__ import annotations

from dataclasses import dataclass
import logging
from io import StringIO
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)
BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageError(RuntimeError):
    """A sanitized error: provider bodies, URLs and credentials are not exposed."""

    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(f"Alpha Vantage request failed ({kind})")


@dataclass(frozen=True)
class JSONResponse:
    payload: dict
    body: bytes


class AlphaVantageRESTClient:
    """REST adapter that rejects HTTP-200 provider errors before caching."""

    def __init__(self, api_key: str):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Alpha Vantage API key is required")
        self.api_key = api_key.strip()
        self.session = requests.Session()

    def _request(self, function: str, params: Optional[dict] = None):
        options = dict(params or {})
        if any(str(key).lower() in {"apikey", "api_key", "function", "token", "password"} for key in options):
            raise ValueError("Request parameters cannot override credentials or function")
        payload = {"function": function, "apikey": self.api_key, **options}
        logger.info("Fetching %s via REST", function)
        try:
            response = self.session.get(BASE_URL, params=payload, timeout=(10, 60), allow_redirects=False)
        except requests.RequestException:
            raise AlphaVantageError("transport") from None
        if response.status_code != 200:
            raise AlphaVantageError(f"http_{response.status_code}")
        if self.api_key.encode() in response.content:
            raise AlphaVantageError("credential_echo")
        return response

    @staticmethod
    def _validate_json(payload):
        if not isinstance(payload, dict) or not payload:
            raise AlphaVantageError("invalid_or_empty_json")
        # Limits/entitlement messages often arrive with HTTP 200.
        if any(key in payload for key in ("Information", "Note", "Error Message")):
            raise AlphaVantageError("provider_notice_or_error")

    def fetch_json_response(self, function: str, params: Optional[dict] = None) -> JSONResponse:
        response = self._request(function, params)
        try:
            payload = response.json()
        except ValueError:
            raise AlphaVantageError("invalid_json") from None
        self._validate_json(payload)
        return JSONResponse(payload, response.content)

    def fetch_json(self, function: str, params: Optional[dict] = None) -> dict:
        return self.fetch_json_response(function, params).payload

    def fetch_time_series_csv(
        self, function: str, symbol: str, outputsize: str = "full", adjusted: bool = True,
    ) -> pd.DataFrame:
        params = {"symbol": symbol, "datatype": "csv", "outputsize": outputsize}
        if function == "TIME_SERIES_INTRADAY" and not adjusted:
            params["adjusted"] = "false"
        response = self._request(function, params)
        if response.text.lstrip().startswith(("{", "[")):
            try:
                self._validate_json(response.json())
            except ValueError:
                raise AlphaVantageError("invalid_json") from None
            raise AlphaVantageError("unexpected_json_for_csv")
        try:
            frame = pd.read_csv(StringIO(response.text))
        except (ValueError, pd.errors.ParserError):
            raise AlphaVantageError("invalid_csv") from None
        frame.columns = [str(column).strip().lower() for column in frame.columns]
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        if frame.empty or not required.issubset(frame):
            raise AlphaVantageError("invalid_time_series_schema")
        frame["symbol"] = symbol
        return frame
