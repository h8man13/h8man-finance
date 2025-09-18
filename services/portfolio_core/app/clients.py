"""External service clients used by portfolio_core."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

import httpx

from .settings import settings


@dataclass(slots=True)
class Quote:
    symbol: str
    price_eur: Decimal
    currency: str
    market: str
    freshness: Optional[str] = None


@dataclass(slots=True)
class QuoteCacheEntry:
    quote: Quote
    expires_at: datetime


@dataclass(slots=True)
class Meta:
    symbol: str
    asset_class: Optional[str]
    market: Optional[str]
    currency: Optional[str]


@dataclass(slots=True)
class MetaCacheEntry:
    meta: Meta
    expires_at: datetime


@dataclass(slots=True)
class BenchmarkCacheEntry:
    data: Dict[str, Any]
    expires_at: datetime


class MarketDataClient:
    """Async client with simple TTL caches for market data service."""

    def __init__(self) -> None:
        self._base_url = settings.MARKET_DATA_BASE_URL.rstrip("/")
        self._timeout = settings.MARKET_DATA_TIMEOUT_SEC
        self._retries = settings.MARKET_DATA_RETRIES
        self._quotes_ttl = settings.QUOTES_CACHE_TTL_SEC
        self._meta_ttl = settings.META_CACHE_TTL_SEC
        self._bench_ttl = settings.BENCHMARK_CACHE_TTL_SEC
        self._http_client: Optional[httpx.AsyncClient] = None
        self._quote_cache: Dict[str, QuoteCacheEntry] = {}
        self._meta_cache: Dict[str, MetaCacheEntry] = {}
        self._bench_cache: Dict[str, BenchmarkCacheEntry] = {}
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            timeout = httpx.Timeout(self._timeout)
            self._http_client = httpx.AsyncClient(timeout=timeout)
        return self._http_client

    async def close(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def clear_cache(self) -> None:
        self._quote_cache.clear()
        self._meta_cache.clear()
        self._bench_cache.clear()

    # ------------------------------------------------------------------ utilities

    def _expired(self, expires_at: datetime) -> bool:
        return datetime.now(timezone.utc) >= expires_at

    # --------------------------------------------------------------------- quotes

    async def get_quotes(self, symbols: Iterable[str], *, force_refresh: bool = False) -> Dict[str, Quote]:
        canonical = [s.upper() for s in symbols if s]
        if not canonical:
            return {}
        cached: Dict[str, Quote] = {}
        missing: List[str] = []
        now_utc = datetime.now(timezone.utc)
        for sym in canonical:
            if not force_refresh:
                entry = self._quote_cache.get(sym)
                if entry and not self._expired(entry.expires_at):
                    cached[sym] = entry.quote
                    continue
            missing.append(sym)
        if missing:
            try:
                fetched = await self._fetch_quotes(missing)
            except httpx.HTTPError:
                fetched = {}
            cached.update(fetched)
        return cached

    async def _fetch_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        client = await self._get_client()
        joined = ",".join(symbols)
        last_exc: Optional[Exception] = None
        for attempt in range(self._retries + 1):
            try:
                response = await client.get(f"{self._base_url}/quote", params={"symbols": joined})
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok"):
                    raise RuntimeError(payload.get("error", {}).get("message", "quote request failed"))
                quotes: Dict[str, Quote] = {}
                for item in payload.get("data", {}).get("quotes", []):
                    raw_symbol = str(item.get("symbol", "")).upper()
                    price_eur = Decimal(str(item.get("price_eur")))
                    currency = str(item.get("currency", "")).upper() or "EUR"
                    market = str(item.get("market", "")).upper() or "-"
                    freshness = item.get("freshness")
                    quote = Quote(raw_symbol, price_eur, currency, market, freshness)
                    entry = QuoteCacheEntry(
                        quote=quote,
                        expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._quotes_ttl),
                    )
                    self._quote_cache[raw_symbol] = entry
                    quotes[raw_symbol] = quote
                    for requested_symbol in symbols:
                        req_norm = requested_symbol.upper()
                        if req_norm != raw_symbol and req_norm.startswith(f"{raw_symbol}."):
                            self._quote_cache[req_norm] = entry
                            quotes[req_norm] = quote
                return quotes
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self._retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
                else:
                    break
        raise RuntimeError(f"quote lookup failed: {last_exc}")

    # ----------------------------------------------------------------------- meta

    async def get_meta(self, symbols: Iterable[str]) -> Dict[str, Meta]:
        canonical = [s.upper() for s in symbols if s]
        if not canonical:
            return {}
        cached: Dict[str, Meta] = {}
        missing: List[str] = []
        for sym in canonical:
            entry = self._meta_cache.get(sym)
            if entry and not self._expired(entry.expires_at):
                cached[sym] = entry.meta
            else:
                missing.append(sym)
        if missing:
            try:
                fetched = await self._fetch_meta(missing)
            except httpx.HTTPError:
                fetched = {}
            cached.update(fetched)
        return cached

    async def _fetch_meta(self, symbols: List[str]) -> Dict[str, Meta]:
        client = await self._get_client()
        meta_map: Dict[str, Meta] = {}

        # Make individual calls since /meta only accepts single symbol parameter
        for symbol in symbols:
            last_exc: Optional[Exception] = None
            for attempt in range(self._retries + 1):
                try:
                    response = await client.get(f"{self._base_url}/meta", params={"symbol": symbol})
                    response.raise_for_status()
                    payload = response.json()
                    if not payload.get("ok"):
                        raise RuntimeError(payload.get("error", {}).get("message", "meta request failed"))

                    data = payload.get("data", {})
                    symbol_upper = str(data.get("symbol", symbol)).upper()
                    meta = Meta(
                        symbol=symbol_upper,
                        asset_class=data.get("asset_class"),
                        market=data.get("market"),
                        currency=data.get("currency"),
                    )
                    self._meta_cache[symbol_upper] = MetaCacheEntry(
                        meta=meta,
                        expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._meta_ttl),
                    )
                    meta_map[symbol_upper] = meta
                    break  # Success, move to next symbol
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt < self._retries:
                        await asyncio.sleep(0.2 * (attempt + 1))
                    else:
                        # If this symbol fails after all retries, continue with others
                        break

        if not meta_map and symbols:
            raise RuntimeError(f"meta lookup failed for all symbols: {last_exc}")
        return meta_map

    # -------------------------------------------------------------- benchmarks

    async def get_benchmarks(self, symbols: List[str], period: str) -> Dict[str, Any]:
        key = f"{period}|{','.join(sorted(symbols))}"
        entry = self._bench_cache.get(key)
        if entry and not self._expired(entry.expires_at):
            return entry.data
        client = await self._get_client()
        joined = ",".join(symbols)
        last_exc: Optional[Exception] = None
        for attempt in range(self._retries + 1):
            try:
                response = await client.get(
                    f"{self._base_url}/benchmarks",
                    params={"period": period, "symbols": joined},
                )
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok"):
                    raise RuntimeError(payload.get("error", {}).get("message", "benchmarks request failed"))
                data = payload.get("data", {})
                self._bench_cache[key] = BenchmarkCacheEntry(
                    data=data,
                    expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._bench_ttl),
                )
                return data
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self._retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
                else:
                    break
        return {}


market_data_client = MarketDataClient()



