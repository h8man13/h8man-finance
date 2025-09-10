from __future__ import annotations

from typing import Any, Dict

from ..settings import get_settings
from .http import HTTPClient


class PortfolioCoreClient:
    def __init__(self, http: HTTPClient):
        self.http = http
        self.base = get_settings().PORTFOLIO_CORE_URL.rstrip("/")

    async def post_buy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base}/tx/buy"
        resp = await self.http.request("POST", url, json=payload)
        return resp.json()

    async def post_sell(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base}/tx/sell"
        resp = await self.http.request("POST", url, json=payload)
        return resp.json()

