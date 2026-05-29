from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests

logger = logging.getLogger(__name__)


class AlphaVantageMCPClient:
    """
    Lightweight JSON-RPC client for the Alpha Vantage MCP HTTP endpoint.
    """

    def __init__(self, api_key: str, base_url: str = "https://mcp.alphavantage.co/mcp") -> None:
        if "apikey=" in base_url:
            self.base_url = base_url
        else:
            self.base_url = f"{base_url}?apikey={api_key}"
        self.session = requests.Session()

    def _rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        resp = self.session.post(self.base_url, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"MCP error {data['error']}")
        return data.get("result", {})

    def list_tools(self) -> List[Dict[str, Any]]:
        result = self._rpc("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        logger.info("Calling Alpha Vantage MCP tool %s", name)
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content")
        return content
