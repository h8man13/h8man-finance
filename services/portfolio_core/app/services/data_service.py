"""
Data service with graceful degradation and fallback logic.

This service integrates the FX and Market Data adapters with intelligent
fallback strategies when external services are unavailable.
"""
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from datetime import datetime, timezone
import logging

from ..adapters import fx_client, market_data_client, FxRate, Quote, SymbolMeta
from ..models import UserContext

logger = logging.getLogger(__name__)


class DataService:
    """
    Provides unified access to external data with graceful degradation.

    Features:
    - Automatic fallback when services unavailable
    - Batch operations for performance
    - Consistent error handling
    - Data freshness indicators
    """

    def __init__(self, user_context: UserContext):
        self.user = user_context

    async def get_current_quotes(self, symbols: List[str]) -> Tuple[Dict[str, Quote], Dict[str, str]]:
        """
        Get current quotes for symbols with fallback strategy.

        Returns:
            Tuple of (quotes_dict, freshness_dict)
            freshness values: "real_time", "cached", "unavailable"
        """
        quotes = {}
        freshness = {}

        # Try to get quotes from market data service
        try:
            service_quotes = await market_data_client.get_quotes(symbols)

            for symbol in symbols:
                symbol_upper = symbol.upper()
                if symbol_upper in service_quotes:
                    quote = service_quotes[symbol_upper]
                    quotes[symbol] = quote

                    # Determine freshness based on source and timestamp
                    age_seconds = (datetime.now(timezone.utc) - quote.timestamp).total_seconds()
                    if quote.source == "market_data" and age_seconds < 300:  # 5 minutes
                        freshness[symbol] = "real_time"
                    else:
                        freshness[symbol] = "cached"
                else:
                    freshness[symbol] = "unavailable"
                    logger.warning(f"No quote available for {symbol}")

        except Exception as e:
            logger.error(f"Failed to get quotes from market data service: {e}")
            for symbol in symbols:
                freshness[symbol] = "unavailable"

        return quotes, freshness

    async def get_symbols_metadata(self, symbols: List[str]) -> Dict[str, SymbolMeta]:
        """
        Get symbol metadata with fallback to defaults.

        Always returns metadata, using intelligent defaults when service unavailable.
        """
        try:
            return await market_data_client.get_symbols_meta(symbols)
        except Exception as e:
            logger.error(f"Failed to get metadata from market data service: {e}")

            # Use fallback parsing for all symbols
            metadata = {}
            for symbol in symbols:
                fallback_meta = market_data_client._parse_symbol_defaults(symbol)
                metadata[symbol.upper()] = fallback_meta
                logger.warning(f"Using fallback metadata for {symbol}")

            return metadata

    async def convert_currency(
        self,
        amount: Decimal,
        from_ccy: str,
        to_ccy: str
    ) -> Tuple[Optional[Decimal], str]:
        """
        Convert currency amount with fallback strategy.

        Returns:
            Tuple of (converted_amount, rate_source)
            rate_source values: "fx_service", "cached", "fallback", "unavailable"
        """
        try:
            rate = await fx_client.get_rate(from_ccy, to_ccy)

            if rate:
                converted = amount * rate.rate

                # Determine source quality
                if rate.source == "fx_service":
                    age_seconds = (datetime.now(timezone.utc) - rate.timestamp).total_seconds()
                    source = "fx_service" if age_seconds < 600 else "cached"  # 10 minutes
                else:
                    source = rate.source  # "fallback", "fallback_inverse", etc.

                return converted, source
            else:
                logger.error(f"No FX rate available for {from_ccy}/{to_ccy}")
                return None, "unavailable"

        except Exception as e:
            logger.error(f"Currency conversion failed: {e}")
            return None, "unavailable"

    async def batch_convert_currency(
        self,
        amounts_and_currencies: List[Tuple[Decimal, str, str]]
    ) -> List[Tuple[Optional[Decimal], str]]:
        """
        Batch currency conversion with fallback strategy.

        Args:
            amounts_and_currencies: List of (amount, from_ccy, to_ccy) tuples

        Returns:
            List of (converted_amount, rate_source) tuples
        """
        # Extract unique currency pairs
        currency_pairs = list(set([(from_ccy, to_ccy) for _, from_ccy, to_ccy in amounts_and_currencies]))

        try:
            # Batch fetch FX rates
            rates = await fx_client.get_rates(currency_pairs)

            results = []
            for amount, from_ccy, to_ccy in amounts_and_currencies:
                key = fx_client._cache_key(from_ccy, to_ccy)

                if key in rates:
                    rate = rates[key]
                    converted = amount * rate.rate

                    # Determine source quality
                    if rate.source == "fx_service":
                        age_seconds = (datetime.now(timezone.utc) - rate.timestamp).total_seconds()
                        source = "fx_service" if age_seconds < 600 else "cached"
                    else:
                        source = rate.source

                    results.append((converted, source))
                else:
                    results.append((None, "unavailable"))

            return results

        except Exception as e:
            logger.error(f"Batch currency conversion failed: {e}")
            return [(None, "unavailable")] * len(amounts_and_currencies)

    async def enrich_positions_with_current_data(
        self,
        positions: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        """
        Enrich positions with current quotes and metadata.

        Returns:
            Tuple of (enriched_positions, data_quality_report)
        """
        if not positions:
            return [], {}

        symbols = [p["symbol"] for p in positions]

        # Get current quotes and metadata in parallel
        quotes, quote_freshness = await self.get_current_quotes(symbols)
        metadata = await self.get_symbols_metadata(symbols)

        enriched_positions = []
        data_quality = {}

        for position in positions:
            symbol = position["symbol"]
            enriched_pos = position.copy()

            # Add current quote if available
            if symbol in quotes:
                quote = quotes[symbol]
                enriched_pos.update({
                    "current_price_ccy": quote.price,
                    "current_price_currency": quote.currency,
                    "quote_timestamp": quote.timestamp.isoformat(),
                    "quote_source": quote.source
                })

                # Calculate current value in original currency
                current_qty = position.get("qty", Decimal("0"))
                enriched_pos["current_value_ccy"] = current_qty * quote.price

            # Add metadata
            symbol_upper = symbol.upper()
            if symbol_upper in metadata:
                meta = metadata[symbol_upper]
                enriched_pos.update({
                    "market": meta.market,
                    "asset_class": meta.asset_class,
                    "currency": meta.currency,
                    "name": meta.name
                })

            # Track data quality
            data_quality[symbol] = {
                "quote_freshness": quote_freshness.get(symbol, "unavailable"),
                "metadata_available": symbol_upper in metadata
            }

            enriched_positions.append(enriched_pos)

        return enriched_positions, data_quality

    async def get_portfolio_real_time_value(
        self,
        positions: List[Dict[str, Any]]
    ) -> Tuple[Decimal, Dict[str, Any]]:
        """
        Calculate real-time portfolio value with data quality metrics.

        Returns:
            Tuple of (total_value_eur, quality_report)
        """
        if not positions:
            return Decimal("0"), {"positions": 0, "real_time": 0, "cached": 0, "fallback": 0}

        enriched_positions, data_quality = await self.enrich_positions_with_current_data(positions)

        total_value = Decimal("0")
        quality_stats = {"positions": len(positions), "real_time": 0, "cached": 0, "fallback": 0}

        for pos in enriched_positions:
            symbol = pos["symbol"]
            qty = pos.get("qty", Decimal("0"))

            if qty <= 0:
                continue

            # Get current value in position currency
            if "current_value_ccy" in pos:
                value_ccy = pos["current_value_ccy"]
                currency = pos.get("current_price_currency", pos.get("currency", "USD"))

                # Convert to EUR
                eur_value, rate_source = await self.convert_currency(value_ccy, currency, "EUR")

                if eur_value:
                    total_value += eur_value

                    # Track quality based on freshness and FX source
                    freshness = data_quality.get(symbol, {}).get("quote_freshness", "unavailable")
                    if freshness == "real_time" and rate_source == "fx_service":
                        quality_stats["real_time"] += 1
                    elif freshness in ["cached", "real_time"] and rate_source in ["cached", "fx_service"]:
                        quality_stats["cached"] += 1
                    else:
                        quality_stats["fallback"] += 1
                else:
                    # Use stored average cost as fallback
                    fallback_value = pos.get("avg_cost_eur", Decimal("0")) * qty
                    total_value += fallback_value
                    quality_stats["fallback"] += 1
            else:
                # Use stored average cost as fallback
                fallback_value = pos.get("avg_cost_eur", Decimal("0")) * qty
                total_value += fallback_value
                quality_stats["fallback"] += 1

        return total_value, quality_stats

    async def health_check(self) -> Dict[str, Any]:
        """Get health status of external services."""
        fx_healthy = await fx_client.health_check()
        market_data_healthy = await market_data_client.health_check()

        return {
            "fx_service": {"healthy": fx_healthy, "cache_entries": len(fx_client.cache)},
            "market_data_service": {
                "healthy": market_data_healthy,
                "cache_stats": market_data_client.get_cache_stats()
            },
            "overall_healthy": fx_healthy and market_data_healthy
        }

    async def clear_caches(self):
        """Clear all service caches."""
        fx_client.cache.clear()
        await market_data_client.clear_cache()
        logger.info("All data service caches cleared")