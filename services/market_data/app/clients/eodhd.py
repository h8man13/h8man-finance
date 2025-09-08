"""
EODHD client used by the quotes service.

Goals:
- Accept symbols like BTC-USD at the API layer; only at the upstream edge
  map to BTC-USD.CC (no hardcoded tickers).
- Parse numbers safely so "N/D" etc. don't crash the request.
- Keep the public contract stable for services/quotes.py (EodhdClient class).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Optional

import httpx

from app.settings import settings
from app.utils.symbols import eodhd_code_from_symbol

EODHD_RT_URL = "https://eodhd.com/api/real-time/{code}"


def _to_decimal(x) -> Optional[Decimal]:
    """Safe Decimal parsing: None/""/"N/D"/non-numeric -> None."""
    if x is None:
        return None
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _pick_price(payload: Dict[str, Any]) -> Optional[Decimal]:
    """Prefer close, then price, then last; tolerate missing/non-numeric."""
    for key in ("close", "price", "last"):
        d = _to_decimal(payload.get(key))
        if d is not None:
            return d
    return None


def _as_of(payload: Dict[str, Any]) -> str:
    """ISO8601 UTC from lastTradeTime/timestamp; fallback to now."""
    ts = payload.get("lastTradeTime") or payload.get("timestamp")
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
        if isinstance(ts, str) and ts:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    return datetime.now(tz=timezone.utc).isoformat()


class EodhdClient:
    """
    Minimal async client. Use like:

        client = EodhdClient()
        data = await client.get_realtime("AMZN.US")
        batch = await client.get_realtime_batch(["AMZN.US","BTC-USD"])

    If you pass your own httpx.AsyncClient, this class won't close it.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 8.0,
    ) -> None:
        self.api_key = api_key or settings.EODHD_API_TOKEN
        self._own_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self.timeout = timeout

    async def aclose(self) -> None:
        if self._own_client:
            await self.client.aclose()

    async def __aenter__(self) -> "EodhdClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def get_realtime(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch a single symbol from EODHD.
        Returns dict with either 'ok': True and 'data' or an 'error' block.
        """
        code = eodhd_code_from_symbol(symbol)
        url = EODHD_RT_URL.format(code=code)
        try:
            r = await self.client.get(
                url,
                params={"api_token": self.api_key, "fmt": "json"},
                timeout=self.timeout,
            )
        except httpx.TimeoutException:
            return {
                "ok": False,
                "error": {
                    "code": "TIMEOUT",
                    "message": "timeout",
                    "source": "eodhd",
                    "retriable": True,
                    "details": {"symbol": symbol},
                },
            }
        except Exception as e:
            return {
                "ok": False,
                "error": {
                    "code": "UPSTREAM_ERROR",
                    "message": str(e),
                    "source": "eodhd",
                    "retriable": True,
                    "details": {"symbol": symbol},
                },
            }

        if r.status_code >= 500:
            return {
                "ok": False,
                "error": {
                    "code": "UPSTREAM_ERROR",
                    "message": f"HTTP {r.status_code}",
                    "source": "eodhd",
                    "retriable": True,
                    "details": {"symbol": symbol},
                },
            }
        if r.status_code == 404:
            return {
                "ok": False,
                "error": {
                    "code": "NOT_FOUND",
                    "message": "symbol not found",
                    "source": "eodhd",
                    "retriable": False,
                    "details": {"symbol": symbol},
                },
            }

        try:
            data = r.json()
            if isinstance(data, list) and data:
                data = data[0]
        except Exception:
            return {
                "ok": False,
                "error": {
                    "code": "UPSTREAM_ERROR",
                    "message": "invalid json",
                    "source": "eodhd",
                    "retriable": True,
                    "details": {"symbol": symbol},
                },
            }

        price = _pick_price(data)
        if price is None or price <= 0:
            return {
                "ok": False,
                "error": {
                    "code": "UPSTREAM_BAD_DATA",
                    "message": "no valid price",
                    "source": "eodhd",
                    "retriable": True,
                    "details": {
                        "symbol": symbol,
                        "raw": {"close": data.get("close"), "price": data.get("price"), "last": data.get("last")},
                    },
                },
            }

        return {
            "ok": True,
            "data": {
                "price": price,        # native currency
                "as_of": _as_of(data), # ISO8601 UTC
                "raw": {"code": code}, # minimal echo
            },
        }

    async def get_realtime_batch(self, symbols: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """Concurrent single calls; returns dict keyed by original symbol."""
        syms = list(symbols)

        async def one(s: str):
            return s, await self.get_realtime(s)

        pairs = await asyncio.gather(*(one(s) for s in syms), return_exceptions=False)
        return {k: v for k, v in pairs}
