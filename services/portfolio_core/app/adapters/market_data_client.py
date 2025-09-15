"""
Market data service adapter with batching, caching, and timeout handling.
"""
from typing import Dict, List, Optional, Set
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import asyncio
import httpx
import logging
from dataclasses import dataclass
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class Quote:
    """Market quote response."""
    symbol: str
    price: Decimal
    currency: str
    timestamp: datetime
    source: str = "market_data"


@dataclass
class SymbolMeta:
    """Symbol metadata response."""
    symbol: str
    market: str
    asset_class: str
    currency: str
    name: Optional[str] = None
    isin: Optional[str] = None


@dataclass
class QuoteCacheEntry:
    """Cache entry for quotes."""
    quote: Quote
    expires_at: datetime


@dataclass
class MetaCacheEntry:
    """Cache entry for symbol metadata."""
    meta: SymbolMeta
    expires_at: datetime


class MarketDataClient:
    """
    Market data service adapter with batching, caching, and graceful degradation.

    Features:
    - Batch requests to minimize API calls
    - Short-term caching with TTL (quotes: 90s, meta: 1h)
    - Timeout handling with retries
    - Graceful fallback when service unavailable
    """

    def __init__(self):
        self.base_url = settings.MARKET_DATA_BASE_URL
        self.timeout = settings.ADAPTER_TIMEOUT_SEC
        self.retry_count = settings.ADAPTER_RETRY_COUNT
        self.quotes_cache_ttl = settings.QUOTES_CACHE_TTL_SEC
        self.meta_cache_ttl = settings.META_CACHE_TTL_SEC
        self.quotes_cache: Dict[str, QuoteCacheEntry] = {}
        self.meta_cache: Dict[str, MetaCacheEntry] = {}
        self._client: Optional[httpx.AsyncClient] = None

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

    def _is_cache_valid(self, expires_at: datetime) -> bool:
        """Check if cache entry is still valid."""
        return datetime.now(timezone.utc) < expires_at

    def _get_quote_from_cache(self, symbol: str) -> Optional[Quote]:
        """Get quote from cache if valid."""
        entry = self.quotes_cache.get(symbol.upper())

        if entry and self._is_cache_valid(entry.expires_at):
            logger.debug(f"Quote cache hit for {symbol}")
            return entry.quote

        # Clean expired entry
        if entry:
            del self.quotes_cache[symbol.upper()]

        return None

    def _cache_quote(self, quote: Quote):
        """Cache quote with TTL."""
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.quotes_cache_ttl)
        self.quotes_cache[quote.symbol.upper()] = QuoteCacheEntry(
            quote=quote,
            expires_at=expires_at
        )

    def _get_meta_from_cache(self, symbol: str) -> Optional[SymbolMeta]:
        """Get symbol metadata from cache if valid."""
        entry = self.meta_cache.get(symbol.upper())

        if entry and self._is_cache_valid(entry.expires_at):
            logger.debug(f"Meta cache hit for {symbol}")
            return entry.meta

        # Clean expired entry
        if entry:
            del self.meta_cache[symbol.upper()]

        return None

    def _cache_meta(self, meta: SymbolMeta):
        """Cache symbol metadata with TTL."""
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.meta_cache_ttl)
        self.meta_cache[meta.symbol.upper()] = MetaCacheEntry(
            meta=meta,
            expires_at=expires_at
        )

    def _parse_symbol_defaults(self, symbol: str) -> SymbolMeta:
        """Parse symbol to determine likely market and asset class."""
        symbol_upper = symbol.upper()

        # Default parsing logic based on symbol format
        if ".US" in symbol_upper:
            market = "US"
            asset_class = "stock" if not any(x in symbol_upper for x in ["ETF", "VTI", "SPY", "QQQ"]) else "etf"
            currency = "USD"
        elif ".L" in symbol_upper or ".LSE" in symbol_upper:
            market = "UK"
            asset_class = "stock"
            currency = "GBP"
        elif ".DE" in symbol_upper or ".XETRA" in symbol_upper:
            market = "DE"
            asset_class = "stock"
            currency = "EUR"
        elif any(x in symbol_upper for x in ["BTC", "ETH", "ADA", "SOL", "DOT"]):
            market = "crypto"
            asset_class = "crypto"
            currency = "USD"
        elif any(x in symbol_upper for x in ["GOLD", "SILVER", "OIL", "GAS"]):
            market = "commodity"
            asset_class = "commodity"
            currency = "USD"
        else:
            # Generic defaults
            market = "unknown"
            asset_class = "stock"
            currency = "USD"

        return SymbolMeta(
            symbol=symbol,
            market=market,
            asset_class=asset_class,
            currency=currency,
            name=symbol  # Fallback to symbol as name
        )

    async def _fetch_quotes_from_service(self, symbols: List[str]) -> Dict[str, Quote]:
        """Fetch multiple quotes from service in batched request."""
        if not symbols:
            return {}

        try:
            client = await self.get_client()

            # Build batch request
            symbols_str = ",".join(symbols)

            for attempt in range(self.retry_count + 1):
                try:
                    response = await client.get(
                        f"{self.base_url}/quotes",
                        params={"symbols": symbols_str}
                    )

                    if response.status_code == 200:
                        data = response.json()

                        if data.get("ok"):
                            quotes = {}
                            for quote_data in data.get("data", {}).get("quotes", []):
                                quote = Quote(
                                    symbol=quote_data["symbol"],
                                    price=Decimal(str(quote_data["price"])),
                                    currency=quote_data["currency"],
                                    timestamp=datetime.fromisoformat(quote_data["timestamp"]),
                                    source="market_data"
                                )
                                quotes[quote.symbol.upper()] = quote

                                # Cache successful fetches
                                self._cache_quote(quote)

                            return quotes
                        else:
                            logger.error(f"Market data service error: {data.get('error', {}).get('message', 'Unknown error')}")

                    else:
                        logger.error(f"Market data service HTTP {response.status_code}: {response.text}")

                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    if attempt < self.retry_count:
                        await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        logger.warning(f"Market data service timeout, retrying ({attempt + 1}/{self.retry_count})")
                        continue
                    else:
                        logger.error(f"Market data service unavailable after {self.retry_count} retries: {e}")
                        break

                except Exception as e:
                    logger.error(f"Unexpected error fetching quotes: {e}")
                    break

        except Exception as e:
            logger.error(f"Failed to fetch quotes: {e}")

        return {}

    async def _fetch_meta_from_service(self, symbols: List[str]) -> Dict[str, SymbolMeta]:
        """Fetch multiple symbol metadata from service in batched request."""
        if not symbols:
            return {}

        try:
            client = await self.get_client()

            # Build batch request
            symbols_str = ",".join(symbols)

            for attempt in range(self.retry_count + 1):
                try:
                    response = await client.get(
                        f"{self.base_url}/meta",
                        params={"symbols": symbols_str}
                    )

                    if response.status_code == 200:
                        data = response.json()

                        if data.get("ok"):
                            meta_data = {}
                            for meta_item in data.get("data", {}).get("meta", []):
                                meta = SymbolMeta(
                                    symbol=meta_item["symbol"],
                                    market=meta_item["market"],
                                    asset_class=meta_item["asset_class"],
                                    currency=meta_item["currency"],
                                    name=meta_item.get("name"),
                                    isin=meta_item.get("isin")
                                )
                                meta_data[meta.symbol.upper()] = meta

                                # Cache successful fetches
                                self._cache_meta(meta)

                            return meta_data
                        else:
                            logger.error(f"Market data service error: {data.get('error', {}).get('message', 'Unknown error')}")

                    else:
                        logger.error(f"Market data service HTTP {response.status_code}: {response.text}")

                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    if attempt < self.retry_count:
                        await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        logger.warning(f"Market data service timeout, retrying ({attempt + 1}/{self.retry_count})")
                        continue
                    else:
                        logger.error(f"Market data service unavailable after {self.retry_count} retries: {e}")
                        break

                except Exception as e:
                    logger.error(f"Unexpected error fetching metadata: {e}")
                    break

        except Exception as e:
            logger.error(f"Failed to fetch metadata: {e}")

        return {}

    async def get_quote(self, symbol: str) -> Optional[Quote]:
        """Get single quote with caching and fallback."""
        # Check cache first
        cached_quote = self._get_quote_from_cache(symbol)
        if cached_quote:
            return cached_quote

        # Fetch from service
        quotes = await self._fetch_quotes_from_service([symbol])
        key = symbol.upper()

        if key in quotes:
            return quotes[key]

        logger.warning(f"No quote available for {symbol}")
        return None

    async def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        """
        Get multiple quotes with batching and caching.

        Args:
            symbols: List of symbol strings

        Returns:
            Dict mapping symbol to Quote
        """
        results = {}
        missing_symbols = []

        # Check cache first
        for symbol in symbols:
            cached_quote = self._get_quote_from_cache(symbol)
            if cached_quote:
                results[symbol.upper()] = cached_quote
            else:
                missing_symbols.append(symbol)

        # Batch fetch missing quotes
        if missing_symbols:
            fetched_quotes = await self._fetch_quotes_from_service(missing_symbols)
            results.update(fetched_quotes)

        return results

    async def get_symbol_meta(self, symbol: str) -> Optional[SymbolMeta]:
        """Get single symbol metadata with caching and fallback."""
        # Check cache first
        cached_meta = self._get_meta_from_cache(symbol)
        if cached_meta:
            return cached_meta

        # Fetch from service
        meta_data = await self._fetch_meta_from_service([symbol])
        key = symbol.upper()

        if key in meta_data:
            return meta_data[key]

        # Use fallback parsing
        logger.warning(f"Using fallback metadata for {symbol}")
        fallback_meta = self._parse_symbol_defaults(symbol)
        self._cache_meta(fallback_meta)  # Cache fallback for consistency
        return fallback_meta

    async def get_symbols_meta(self, symbols: List[str]) -> Dict[str, SymbolMeta]:
        """
        Get multiple symbol metadata with batching, caching, and fallback.

        Args:
            symbols: List of symbol strings

        Returns:
            Dict mapping symbol to SymbolMeta
        """
        results = {}
        missing_symbols = []

        # Check cache first
        for symbol in symbols:
            cached_meta = self._get_meta_from_cache(symbol)
            if cached_meta:
                results[symbol.upper()] = cached_meta
            else:
                missing_symbols.append(symbol)

        # Batch fetch missing metadata
        if missing_symbols:
            fetched_meta = await self._fetch_meta_from_service(missing_symbols)
            results.update(fetched_meta)

            # Use fallbacks for any still missing
            for symbol in missing_symbols:
                key = symbol.upper()
                if key not in results:
                    logger.warning(f"Using fallback metadata for {symbol}")
                    fallback_meta = self._parse_symbol_defaults(symbol)
                    self._cache_meta(fallback_meta)
                    results[key] = fallback_meta

        return results

    async def health_check(self) -> bool:
        """Check if market data service is healthy."""
        try:
            client = await self.get_client()
            response = await client.get(f"{self.base_url}/health", timeout=2.0)
            return response.status_code == 200
        except Exception:
            return False

    async def clear_cache(self):
        """Clear all cached data."""
        self.quotes_cache.clear()
        self.meta_cache.clear()
        logger.info("Market data cache cleared")

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        now = datetime.now(timezone.utc)
        valid_quotes = sum(1 for entry in self.quotes_cache.values()
                          if self._is_cache_valid(entry.expires_at))
        valid_meta = sum(1 for entry in self.meta_cache.values()
                        if self._is_cache_valid(entry.expires_at))

        return {
            "quotes_cached": len(self.quotes_cache),
            "quotes_valid": valid_quotes,
            "meta_cached": len(self.meta_cache),
            "meta_valid": valid_meta
        }


# Global market data client instance
market_data_client = MarketDataClient()