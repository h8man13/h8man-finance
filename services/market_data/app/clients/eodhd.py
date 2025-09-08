"""
EODHD provider, edge hardened.

Goals:
- Accept public symbols like BTC-USD, transform to EODHD code BTC-USD.CC only at the provider edge.
- Parse numbers safely to avoid decimal.ConversionSyntax when EODHD returns N/D or empty fields.
- Do not change public API contracts outside this module.

Interface (expected usage from your service layer):
    async def get_realtime(session, api_key, symbol) -> dict
    async def get_realtime_batch(session, api_key, symbols) -> dict[str, dict]
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List

import httpx

from app.utils.symbols import eodhd_code_from_symbol

EODHD_RT_URL = "https://eodhd.com/api/real-time/{code}"

def _to_decimal(x) -> Decimal | None:
    """
    Safe Decimal parsing:
    - None, "", "N/D", or other non numeric strings return None.
    - Use str(x) to keep ints and floats precise and uniform.
    """
    if x is None:
        return None
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return None

def _pick_price(payload: Dict[str, Any]) -> Decimal | None:
    """
    Prefer 'close', then 'price', then 'last'.
    Tolerates missing or non numeric fields.
    """
    for key in ("close", "price", "last"):
        d = _to_decimal(payload.get(key))
        if d is not None:
            return d
    return None

def _as_of(payload: Dict[str, Any]) -> str:
    """
    Derive ISO8601 UTC timestamp from lastTradeTime or timestamp when available.
    Fall back to now in UTC.
    """
    ts = payload.get("lastTradeTime") or payload.get("timestamp")
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
        if isinstance(ts, str) and ts:
            # normalize to aware UTC
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    return datetime.now(tz=timezone.utc).isoformat()

async def get_realtime(session: httpx.AsyncClient, api_key: str, symbol: str) -> Dict[str, Any]:
    """
    Fetch a single symbol from EODHD.
    Returns a dict with either 'data' or 'error'.
    Never raises on upstream formatting issues.
    """
    code = eodhd_code_from_symbol(symbol)
    url = EODHD_RT_URL.format(code=code)

    try:
        r = await session.get(url, params={"api_token": api_key, "fmt": "json"}, timeout=8.0)
    except httpx.TimeoutException:
        return {"ok": False, "error": {"code": "TIMEOUT", "message": "timeout", "source": "eodhd", "retriable": True, "details": {"symbol": symbol}}}
    except Exception as e:
        return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": str(e), "source": "eodhd", "retriable": True, "details": {"symbol": symbol}}}

    if r.status_code >= 500:
        return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": f"HTTP {r.status_code}", "source": "eodhd", "retriable": True, "details": {"symbol": symbol}}}
    if r.status_code == 404:
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "symbol not found", "source": "eodhd", "retriable": False, "details": {"symbol": symbol}}}

    try:
        data = r.json()
        # Some EODHD endpoints sometimes wrap in a list
        if isinstance(data, list) and data:
            data = data[0]
    except Exception:
        return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": "invalid json", "source": "eodhd", "retriable": True, "details": {"symbol": symbol}}}

    price = _pick_price(data)
    if price is None or price <= 0:
        return {"ok": False, "error": {"code": "UPSTREAM_BAD_DATA", "message": "no valid price", "source": "eodhd", "retriable": True, "details": {"symbol": symbol, "raw": {"close": data.get("close"), "price": data.get("price"), "last": data.get("last")}}}}

    return {
        "ok": True,
        "data": {
            "price": price,          # native ccy
            "as_of": _as_of(data),   # ISO8601 UTC
            "raw": {"code": code},   # minimal echo
        },
    }

async def get_realtime_batch(session: httpx.AsyncClient, api_key: str, symbols: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """
    Concurrent calls for simplicity. Caching sits above this layer.
    Returns a dict keyed by the original symbol for easy alignment.
    """
    syms: List[str] = list(symbols)

    async def one(s: str):
        res = await get_realtime(session, api_key, s)
        return s, res

    pairs = await asyncio.gather(*(one(s) for s in syms), return_exceptions=False)
    return {k: v for k, v in pairs}
