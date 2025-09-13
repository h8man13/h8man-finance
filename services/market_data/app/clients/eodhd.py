from __future__ import annotations

import httpx
from typing import List, Dict, Any
from decimal import Decimal, InvalidOperation

from ..settings import settings

# Use shared symbol mapper if present; otherwise a generic, future-proof rule.
try:
    from ..utils.symbols import eodhd_code_from_symbol as _code_map  # optional
except Exception:  # pragma: no cover
    def _code_map(sym: str) -> str:
        s = sym.strip().upper()
        # EODHD expects .CC for crypto pairs like BTC-USD
        if "-" in s and not s.endswith(".CC"):
            return f"{s}.CC"
        return s

def _is_numeric(val) -> bool:
    try:
        Decimal(str(val))
        return True
    except (InvalidOperation, ValueError, TypeError):
        return False

def _sanitize_item(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Make upstream payload safer for downstream Decimal() casts:
    - If 'close' is non-numeric but 'price' or 'last' is numeric,
      copy that numeric value into 'close'. This is generic and
      avoids per-ticker hacks.
    """
    if not _is_numeric(d.get("close")):
        for k in ("price", "last"):
            if _is_numeric(d.get(k)):
                d["close"] = str(d[k])
                break
    # Ensure 'open' is numeric or None
    if not _is_numeric(d.get("open")):
        d["open"] = None
    return d

class EodhdClient:
    def __init__(
        self,
        base_url: str = settings.EODHD_BASE_URL,
        token: str = settings.EODHD_API_TOKEN,
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    async def batch_quotes(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch real-time quotes for multiple symbols in one call.
        Returns the upstream JSON (list of dicts), with a light sanitation
        to avoid Decimal('N/D') crashes downstream.
        """
        codes = ",".join(_code_map(s) for s in symbols)
        url = f"{self.base_url}/real-time/{codes}"
        params = {"api_token": self.token, "fmt": "json"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            items = data if isinstance(data, list) else [data]
            return [_sanitize_item(dict(item)) for item in items]

    async def historical(self, symbol: str, period: str) -> List[Dict[str, Any]]:
        """
        Daily EOD data; 'period' is accepted for interface compatibility.
        """
        code = _code_map(symbol)
        url = f"{self.base_url}/eod/{code}"
        params = {"api_token": self.token, "fmt": "json", "order": "d"}

        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
