"""
FX service adapter with batching, caching, and timeout handling.
"""
from typing import Dict, List, Optional, Set, Tuple
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import asyncio
import httpx
import logging
from dataclasses import dataclass
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class FxRate:
    """FX rate response."""
    from_ccy: str
    to_ccy: str
    rate: Decimal
    timestamp: datetime
    source: str = "fx_service"


@dataclass
class CacheEntry:
    """Cache entry for FX rates."""
    rate: FxRate
    expires_at: datetime


class FxClient:
    """
    FX service adapter with batching, caching, and graceful degradation.

    Features:
    - Batch requests to minimize API calls
    - Short-term caching with TTL
    - Timeout handling with retries
    - Graceful fallback when service unavailable
    """

    def __init__(self):
        self.base_url = settings.FX_BASE_URL
        self.timeout = settings.ADAPTER_TIMEOUT_SEC
        self.retry_count = settings.ADAPTER_RETRY_COUNT
        self.cache_ttl = settings.FX_CACHE_TTL_SEC
        self.cache: Dict[Tuple[str, str], CacheEntry] = {}
        self._client: Optional[httpx.AsyncClient] = None

        # Fallback rates (conservative estimates)
        self.fallback_rates = {
            ("USD", "EUR"): Decimal("0.85"),
            ("EUR", "USD"): Decimal("1.18"),
            ("GBP", "EUR"): Decimal("1.15"),
            ("EUR", "GBP"): Decimal("0.87"),
            ("CHF", "EUR"): Decimal("0.95"),
            ("EUR", "CHF"): Decimal("1.05"),
        }

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers={"User-Agent": "portfolio_core/1.0"}
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _cache_key(self, from_ccy: str, to_ccy: str) -> Tuple[str, str]:
        """Generate cache key for currency pair."""
        return (from_ccy.upper(), to_ccy.upper())

    def _is_cache_valid(self, entry: CacheEntry) -> bool:
        """Check if cache entry is still valid."""
        return datetime.now(timezone.utc) < entry.expires_at

    def _get_from_cache(self, from_ccy: str, to_ccy: str) -> Optional[FxRate]:
        """Get rate from cache if valid."""
        key = self._cache_key(from_ccy, to_ccy)
        entry = self.cache.get(key)

        if entry and self._is_cache_valid(entry):
            logger.debug(f"Cache hit for {from_ccy}/{to_ccy}")
            return entry.rate

        # Clean expired entry
        if entry:
            del self.cache[key]

        return None

    def _cache_rate(self, rate: FxRate):
        """Cache FX rate with TTL."""
        key = self._cache_key(rate.from_ccy, rate.to_ccy)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.cache_ttl)
        self.cache[key] = CacheEntry(rate=rate, expires_at=expires_at)

        # Also cache inverse rate
        inverse_rate = FxRate(
            from_ccy=rate.to_ccy,
            to_ccy=rate.from_ccy,
            rate=Decimal("1") / rate.rate,
            timestamp=rate.timestamp,
            source=rate.source
        )
        inverse_key = self._cache_key(inverse_rate.from_ccy, inverse_rate.to_ccy)
        self.cache[inverse_key] = CacheEntry(rate=inverse_rate, expires_at=expires_at)

    def _get_fallback_rate(self, from_ccy: str, to_ccy: str) -> Optional[FxRate]:
        """Get fallback rate if available."""
        key = (from_ccy.upper(), to_ccy.upper())
        rate = self.fallback_rates.get(key)

        if rate:
            logger.warning(f"Using fallback rate for {from_ccy}/{to_ccy}: {rate}")
            return FxRate(
                from_ccy=from_ccy,
                to_ccy=to_ccy,
                rate=rate,
                timestamp=datetime.now(timezone.utc),
                source="fallback"
            )

        # Try inverse
        inverse_key = (to_ccy.upper(), from_ccy.upper())
        inverse_rate = self.fallback_rates.get(inverse_key)
        if inverse_rate:
            rate = Decimal("1") / inverse_rate
            logger.warning(f"Using inverse fallback rate for {from_ccy}/{to_ccy}: {rate}")
            return FxRate(
                from_ccy=from_ccy,
                to_ccy=to_ccy,
                rate=rate,
                timestamp=datetime.now(timezone.utc),
                source="fallback_inverse"
            )

        return None

    async def _fetch_rates_from_service(self, currency_pairs: List[Tuple[str, str]]) -> Dict[Tuple[str, str], FxRate]:
        """Fetch multiple FX rates from service in batched request."""
        if not currency_pairs:
            return {}

        try:
            client = await self.get_client()

            # Build batch request
            pairs_str = ",".join([f"{from_ccy}{to_ccy}" for from_ccy, to_ccy in currency_pairs])

            for attempt in range(self.retry_count + 1):
                try:
                    response = await client.get(
                        f"{self.base_url}/rates",
                        params={"pairs": pairs_str}
                    )

                    if response.status_code == 200:
                        data = response.json()

                        if data.get("ok"):
                            rates = {}
                            for rate_data in data.get("data", {}).get("rates", []):
                                rate = FxRate(
                                    from_ccy=rate_data["from_ccy"],
                                    to_ccy=rate_data["to_ccy"],
                                    rate=Decimal(str(rate_data["rate"])),
                                    timestamp=datetime.fromisoformat(rate_data["timestamp"]),
                                    source="fx_service"
                                )
                                rates[self._cache_key(rate.from_ccy, rate.to_ccy)] = rate

                                # Cache successful fetches
                                self._cache_rate(rate)

                            return rates
                        else:
                            logger.error(f"FX service error: {data.get('error', {}).get('message', 'Unknown error')}")

                    else:
                        logger.error(f"FX service HTTP {response.status_code}: {response.text}")

                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    if attempt < self.retry_count:
                        await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        logger.warning(f"FX service timeout, retrying ({attempt + 1}/{self.retry_count})")
                        continue
                    else:
                        logger.error(f"FX service unavailable after {self.retry_count} retries: {e}")
                        break

                except Exception as e:
                    logger.error(f"Unexpected error fetching FX rates: {e}")
                    break

        except Exception as e:
            logger.error(f"Failed to fetch FX rates: {e}")

        return {}

    async def get_rate(self, from_ccy: str, to_ccy: str) -> Optional[FxRate]:
        """Get single FX rate with caching and fallback."""
        # Same currency
        if from_ccy.upper() == to_ccy.upper():
            return FxRate(
                from_ccy=from_ccy,
                to_ccy=to_ccy,
                rate=Decimal("1"),
                timestamp=datetime.now(timezone.utc),
                source="identity"
            )

        # Check cache first
        cached_rate = self._get_from_cache(from_ccy, to_ccy)
        if cached_rate:
            return cached_rate

        # Fetch from service
        rates = await self._fetch_rates_from_service([(from_ccy, to_ccy)])
        key = self._cache_key(from_ccy, to_ccy)

        if key in rates:
            return rates[key]

        # Use fallback
        fallback_rate = self._get_fallback_rate(from_ccy, to_ccy)
        if fallback_rate:
            return fallback_rate

        logger.error(f"No FX rate available for {from_ccy}/{to_ccy}")
        return None

    async def get_rates(self, currency_pairs: List[Tuple[str, str]]) -> Dict[Tuple[str, str], FxRate]:
        """
        Get multiple FX rates with batching, caching, and fallback.

        Args:
            currency_pairs: List of (from_ccy, to_ccy) tuples

        Returns:
            Dict mapping (from_ccy, to_ccy) to FxRate
        """
        results = {}
        missing_pairs = []

        # Check cache and handle identity rates
        for from_ccy, to_ccy in currency_pairs:
            key = self._cache_key(from_ccy, to_ccy)

            # Same currency
            if from_ccy.upper() == to_ccy.upper():
                results[key] = FxRate(
                    from_ccy=from_ccy,
                    to_ccy=to_ccy,
                    rate=Decimal("1"),
                    timestamp=datetime.now(timezone.utc),
                    source="identity"
                )
                continue

            # Check cache
            cached_rate = self._get_from_cache(from_ccy, to_ccy)
            if cached_rate:
                results[key] = cached_rate
            else:
                missing_pairs.append((from_ccy, to_ccy))

        # Batch fetch missing rates
        if missing_pairs:
            fetched_rates = await self._fetch_rates_from_service(missing_pairs)
            results.update(fetched_rates)

            # Use fallbacks for any still missing
            for from_ccy, to_ccy in missing_pairs:
                key = self._cache_key(from_ccy, to_ccy)
                if key not in results:
                    fallback_rate = self._get_fallback_rate(from_ccy, to_ccy)
                    if fallback_rate:
                        results[key] = fallback_rate

        return results

    async def convert_amount(self, amount: Decimal, from_ccy: str, to_ccy: str) -> Optional[Decimal]:
        """Convert amount from one currency to another."""
        rate = await self.get_rate(from_ccy, to_ccy)
        if rate:
            return amount * rate.rate
        return None

    async def health_check(self) -> bool:
        """Check if FX service is healthy."""
        try:
            client = await self.get_client()
            response = await client.get(f"{self.base_url}/health", timeout=2.0)
            return response.status_code == 200
        except Exception:
            return False


# Global FX client instance
fx_client = FxClient()