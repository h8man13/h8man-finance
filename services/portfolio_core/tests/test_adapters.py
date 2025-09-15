"""
Tests for external service adapters.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal
from datetime import datetime, timezone

from app.adapters.fx_client import FxClient, FxRate
from app.adapters.market_data_client import MarketDataClient, Quote, SymbolMeta


@pytest.fixture
def fx_client():
    """FX client fixture."""
    return FxClient()


@pytest.fixture
def market_data_client():
    """Market data client fixture."""
    return MarketDataClient()


@pytest.mark.asyncio
async def test_fx_client_cache(fx_client):
    """Test FX client caching functionality."""
    # Mock successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "data": {
            "rates": [{
                "from_ccy": "USD",
                "to_ccy": "EUR",
                "rate": 0.85,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }]
        }
    }

    with patch.object(fx_client, 'get_client') as mock_client:
        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_client.return_value = mock_http_client

        # First call should fetch from service
        rate1 = await fx_client.get_rate("USD", "EUR")
        assert rate1 is not None
        assert rate1.rate == Decimal("0.85")
        assert rate1.source == "fx_service"

        # Second call should use cache
        rate2 = await fx_client.get_rate("USD", "EUR")
        assert rate2 is not None
        assert rate2.rate == Decimal("0.85")

        # Should only have called the service once
        assert mock_http_client.get.call_count == 1


@pytest.mark.asyncio
async def test_fx_client_fallback(fx_client):
    """Test FX client fallback rates."""
    with patch.object(fx_client, 'get_client') as mock_client:
        # Mock service unavailable
        mock_http_client = AsyncMock()
        mock_http_client.get.side_effect = Exception("Service unavailable")
        mock_client.return_value = mock_http_client

        # Should use fallback rate for USD/EUR
        rate = await fx_client.get_rate("USD", "EUR")
        assert rate is not None
        assert rate.source == "fallback"
        assert rate.rate == Decimal("0.85")  # Predefined fallback


@pytest.mark.asyncio
async def test_fx_client_batch_rates(fx_client):
    """Test FX client batch rate fetching."""
    # Mock successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "data": {
            "rates": [
                {
                    "from_ccy": "USD",
                    "to_ccy": "EUR",
                    "rate": 0.85,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                },
                {
                    "from_ccy": "GBP",
                    "to_ccy": "EUR",
                    "rate": 1.15,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            ]
        }
    }

    with patch.object(fx_client, 'get_client') as mock_client:
        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_client.return_value = mock_http_client

        # Batch request
        pairs = [("USD", "EUR"), ("GBP", "EUR")]
        rates = await fx_client.get_rates(pairs)

        assert len(rates) == 2
        assert ("USD", "EUR") in rates
        assert ("GBP", "EUR") in rates
        assert rates[("USD", "EUR")].rate == Decimal("0.85")
        assert rates[("GBP", "EUR")].rate == Decimal("1.15")


@pytest.mark.asyncio
async def test_market_data_client_cache(market_data_client):
    """Test market data client caching functionality."""
    # Mock successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "data": {
            "quotes": [{
                "symbol": "AAPL.US",
                "price": 150.0,
                "currency": "USD",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }]
        }
    }

    with patch.object(market_data_client, 'get_client') as mock_client:
        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_client.return_value = mock_http_client

        # First call should fetch from service
        quote1 = await market_data_client.get_quote("AAPL.US")
        assert quote1 is not None
        assert quote1.price == Decimal("150.0")
        assert quote1.source == "market_data"

        # Second call should use cache
        quote2 = await market_data_client.get_quote("AAPL.US")
        assert quote2 is not None
        assert quote2.price == Decimal("150.0")

        # Should only have called the service once
        assert mock_http_client.get.call_count == 1


@pytest.mark.asyncio
async def test_market_data_client_fallback_metadata(market_data_client):
    """Test market data client fallback metadata."""
    with patch.object(market_data_client, 'get_client') as mock_client:
        # Mock service unavailable
        mock_http_client = AsyncMock()
        mock_http_client.get.side_effect = Exception("Service unavailable")
        mock_client.return_value = mock_http_client

        # Should use fallback metadata
        meta = await market_data_client.get_symbol_meta("AAPL.US")
        assert meta is not None
        assert meta.symbol == "AAPL.US"
        assert meta.market == "US"
        assert meta.asset_class == "stock"
        assert meta.currency == "USD"


@pytest.mark.asyncio
async def test_market_data_client_batch_quotes(market_data_client):
    """Test market data client batch quote fetching."""
    # Mock successful response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "data": {
            "quotes": [
                {
                    "symbol": "AAPL.US",
                    "price": 150.0,
                    "currency": "USD",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                },
                {
                    "symbol": "MSFT.US",
                    "price": 300.0,
                    "currency": "USD",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            ]
        }
    }

    with patch.object(market_data_client, 'get_client') as mock_client:
        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_client.return_value = mock_http_client

        # Batch request
        symbols = ["AAPL.US", "MSFT.US"]
        quotes = await market_data_client.get_quotes(symbols)

        assert len(quotes) == 2
        assert "AAPL.US" in quotes
        assert "MSFT.US" in quotes
        assert quotes["AAPL.US"].price == Decimal("150.0")
        assert quotes["MSFT.US"].price == Decimal("300.0")


@pytest.mark.asyncio
async def test_symbol_defaults_parsing(market_data_client):
    """Test symbol metadata default parsing."""
    # US stock
    meta = market_data_client._parse_symbol_defaults("AAPL.US")
    assert meta.market == "US"
    assert meta.asset_class == "stock"
    assert meta.currency == "USD"

    # UK stock
    meta = market_data_client._parse_symbol_defaults("BP.L")
    assert meta.market == "UK"
    assert meta.asset_class == "stock"
    assert meta.currency == "GBP"

    # German stock
    meta = market_data_client._parse_symbol_defaults("SAP.DE")
    assert meta.market == "DE"
    assert meta.asset_class == "stock"
    assert meta.currency == "EUR"

    # Crypto
    meta = market_data_client._parse_symbol_defaults("BTC-USD")
    assert meta.market == "crypto"
    assert meta.asset_class == "crypto"
    assert meta.currency == "USD"

    # ETF
    meta = market_data_client._parse_symbol_defaults("SPY.US")
    assert meta.market == "US"
    assert meta.asset_class == "etf"
    assert meta.currency == "USD"


@pytest.mark.asyncio
async def test_health_checks(fx_client, market_data_client):
    """Test health check functionality."""
    # Mock healthy responses
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch.object(fx_client, 'get_client') as mock_fx_client, \
         patch.object(market_data_client, 'get_client') as mock_md_client:

        mock_http_client = AsyncMock()
        mock_http_client.get.return_value = mock_response
        mock_fx_client.return_value = mock_http_client
        mock_md_client.return_value = mock_http_client

        # Both should be healthy
        fx_healthy = await fx_client.health_check()
        md_healthy = await market_data_client.health_check()

        assert fx_healthy is True
        assert md_healthy is True


@pytest.mark.asyncio
async def test_cache_stats(market_data_client):
    """Test cache statistics functionality."""
    # Initially empty
    stats = market_data_client.get_cache_stats()
    assert stats["quotes_cached"] == 0
    assert stats["meta_cached"] == 0

    # Add some cache entries manually for testing
    from app.adapters.market_data_client import QuoteCacheEntry, MetaCacheEntry
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=5)

    # Add quote cache entry
    quote = Quote("TEST", Decimal("100"), "USD", now)
    market_data_client.quotes_cache["TEST"] = QuoteCacheEntry(quote, future)

    # Add meta cache entry
    meta = SymbolMeta("TEST", "US", "stock", "USD")
    market_data_client.meta_cache["TEST"] = MetaCacheEntry(meta, future)

    stats = market_data_client.get_cache_stats()
    assert stats["quotes_cached"] == 1
    assert stats["quotes_valid"] == 1
    assert stats["meta_cached"] == 1
    assert stats["meta_valid"] == 1