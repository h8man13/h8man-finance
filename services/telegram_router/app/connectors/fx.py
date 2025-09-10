from __future__ import annotations

from typing import Any, Dict

from ..settings import get_settings
from .http import HTTPClient


class FXClient:
    def __init__(self, http: HTTPClient):
        self.http = http
        self.base = get_settings().FX_URL.rstrip("/")

    async def get_fx(self, *, base: str, quote: str) -> Dict[str, Any]:
        url = f"{self.base}/fx"
        pair = f"{base}_{quote}".upper()
        resp = await self.http.request("GET", url, params={"pair": pair})
        return resp.json()
