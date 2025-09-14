from __future__ import annotations

from typing import Any, Dict

from ..settings import get_settings
from .http import HTTPClient


class FXClient:
    def __init__(self, http: HTTPClient):
        self.http = http
        self.base = get_settings().FX_URL.rstrip("/")

    async def get_fx(self, *, base: str, quote: str, force: bool = False) -> Dict[str, Any]:
        """Request an arbitrary FX pair BASE/QUOTE from the fx service.
        Pair is formatted as BASE_QUOTE (uppercased). Set force=True to bypass cache.
        """
        url = f"{self.base}/fx"
        pair = f"{base}_{quote}".upper()
        params = {"pair": pair}
        if force:
            params["force"] = True
        resp = await self.http.request("GET", url, params=params)
        return resp.json()

    async def refresh_usdeur(self) -> Dict[str, Any]:
        """Force refresh the USD_EUR cache and return the latest rate."""
        url = f"{self.base}/fx"
        resp = await self.http.request("GET", url, params={"pair": "USD_EUR", "force": True})
        return resp.json()
