from __future__ import annotations

from typing import Any, Dict

from ..settings import get_settings
from .http import HTTPClient


class FXClient:
    def __init__(self, http: HTTPClient):
        self.http = http
        self.base = get_settings().FX_URL.rstrip("/")

    async def get_fx(self, *, base: str, quote: str) -> Dict[str, Any]:
        """
        The FX microservice only supports USD_EUR. Always request USD_EUR
        and let the caller invert when needed for display.
        """
        url = f"{self.base}/fx"
        resp = await self.http.request("GET", url, params={"pair": "USD_EUR"})
        return resp.json()

    async def refresh_usdeur(self) -> Dict[str, Any]:
        """Force refresh the USD_EUR cache and return the latest rate."""
        url = f"{self.base}/fx"
        resp = await self.http.request("GET", url, params={"pair": "USD_EUR", "force": True})
        return resp.json()
