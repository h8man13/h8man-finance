"""
FX service adapter for currency conversion.
"""
import httpx
from typing import Dict, Any, Optional
from decimal import Decimal

from ..settings import settings


class FxAdapter:
    """Adapter for FX service communication."""

    def __init__(self):
        self.base_url = settings.FX_URL
        self.timeout = httpx.Timeout(10.0)

    async def get_eur_rate(self, pair: str) -> Optional[Decimal]:
        """Get EUR conversion rate for currency pair."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/fx", params={"pair": pair})
                data = response.json()

                if not data.get("ok", False):
                    return None

                return Decimal(str(data.get("rate", "1.0")))
        except Exception:
            # Fallback rate for demo
            return Decimal("0.9") if pair == "USD_EUR" else Decimal("1.0")


# Singleton instance
fx_adapter = FxAdapter()