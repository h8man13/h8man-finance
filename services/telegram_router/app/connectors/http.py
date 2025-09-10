from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import httpx


class HTTPClient:
    def __init__(self, timeout: float = 8.0, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self._client = httpx.AsyncClient(timeout=self.timeout)

    async def request(self, method: str, url: str, *, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None) -> httpx.Response:
        method_u = method.upper()
        attempts = self.retries + 1 if (method_u == "GET" and self.retries > 0) else 1
        last_exc: Optional[Exception] = None
        for i in range(attempts):
            try:
                resp = await self._client.request(method_u, url, params=params, json=json)
                return resp
            except Exception as e:
                last_exc = e
                if i < attempts - 1:
                    await asyncio.sleep(0.2 * (i + 1))
        assert last_exc is not None
        raise last_exc

    async def close(self):
        await self._client.aclose()

