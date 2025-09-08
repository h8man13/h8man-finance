import httpx
from typing import List, Dict, Any
from ..settings import settings

class EodhdClient:
    def __init__(self, base_url: str = settings.EODHD_BASE_URL, token: str = settings.EODHD_API_TOKEN):
        self.base_url = base_url.rstrip("/")
        self.token = token

    async def batch_quotes(self, symbols: List[str]) -> List[Dict[str, Any]]:
        # Real-time quotes, prefer batch to save cost per spec
        # Endpoint shape per EODHD docs: /real-time/{symbols}?api_token=...
        syms = ",".join(symbols)
        url = f"{self.base_url}/real-time/{syms}?api_token={self.token}&fmt=json"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json() if isinstance(r.json(), list) else [r.json()]

    async def historical(self, symbol: str, period: str) -> List[Dict[str, Any]]:
        # Use historical endpoint, daily bars, we will select per bucket rules in service
        url = f"{self.base_url}/eod/{symbol}?api_token={self.token}&fmt=json&order=d"
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
