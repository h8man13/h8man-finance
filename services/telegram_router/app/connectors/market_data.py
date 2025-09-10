from __future__ import annotations

from typing import Any, Dict, List

from ..settings import get_settings
from .http import HTTPClient


class MarketDataClient:
    def __init__(self, http: HTTPClient):
        self.http = http
        self.base = get_settings().MARKET_DATA_URL.rstrip("/")

    async def get_quotes(self, *, symbols: List[str]) -> Dict[str, Any]:
        url = f"{self.base}/quote"
        params = {"symbols": ",".join(symbols)}
        resp = await self.http.request("GET", url, params=params)
        return resp.json()

    async def get_benchmarks(self, *, period: str, symbols: List[str]) -> Dict[str, Any]:
        url = f"{self.base}/benchmarks"
        params = {"period": period, "symbols": ",".join(symbols)}
        resp = await self.http.request("GET", url, params=params)
        return resp.json()
