import httpx
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict
from ..settings import settings

class FxClient:
    def __init__(self, base_url: str = settings.FX_BASE_URL):
        self.base_url = base_url.rstrip("/")

    async def usd_to_eur(self) -> Decimal:
        url = f"{self.base_url}/fx?pair=USD_EUR"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            rate = Decimal(str(data.get("rate")))
            return rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
