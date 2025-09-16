"""
Tests for the data service with graceful degradation.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal
from datetime import datetime, timezone

from app.services.data_service import DataService
from app.models import UserContext
from app.adapters.fx_client import FxRate
from app.adapters.market_data_client import Quote, SymbolMeta


@pytest.fixture
def user_context():
    """User context fixture."""
    return UserContext(
        user_id=12345,
        first_name="Test",
        last_name="User",
        username="testuser",
        language_code="en"
    )


@pytest.fixture
def data_service(user_context):
    """Data service fixture."""
    return DataService(user_context)


@pytest.fixture
def mock_positions():
    """Mock positions data."""
    return [
        {
            "symbol": "AAPL.US",
            "qty": Decimal("10"),
            "avg_cost_ccy": Decimal("150.0"),
            "avg_cost_eur": Decimal("127.5"),
            "ccy": "USD"
        },
        {
            "symbol": "MSFT.US",
            "qty": Decimal("5"),
            "avg_cost_ccy": Decimal("300.0"),
            "avg_cost_eur": Decimal("255.0"),
            "ccy": "USD"
        }
    ]


@pytest.mark.asyncio
async def test_get_current_quotes_success(data_service):
    """Test successful quote retrieval."""
    symbols = ["AAPL.US", "MSFT.US"]

    # Mock market data client
    mock_quotes = {
        "AAPL.US": Quote("AAPL.US", Decimal("160.0"), "USD", datetime.now(timezone.utc)),
        "MSFT.US": Quote("MSFT.US", Decimal("320.0"), "USD", datetime.now(timezone.utc))
    }

    with patch('app.services.data_service.market_data_client') as mock_client:
        mock_client.get_quotes = AsyncMock(return_value=mock_quotes)

        quotes, freshness = await data_service.get_current_quotes(symbols)

        assert len(quotes) == 2
        assert "AAPL.US" in quotes
        assert "MSFT.US" in quotes
        assert quotes["AAPL.US"].price == Decimal("160.0")
        assert freshness["AAPL.US"] == "real_time"
        assert freshness["MSFT.US"] == "real_time"


@pytest.mark.asyncio
async def test_get_current_quotes_service_failure(data_service):
    """Test quote retrieval when service fails."""
    symbols = ["AAPL.US", "MSFT.US"]

    with patch('app.services.data_service.market_data_client') as mock_client:
        mock_client.get_quotes = AsyncMock(side_effect=Exception("Service unavailable"))

        quotes, freshness = await data_service.get_current_quotes(symbols)

        assert len(quotes) == 0
        assert freshness["AAPL.US"] == "unavailable"
        assert freshness["MSFT.US"] == "unavailable"


@pytest.mark.asyncio
async def test_convert_currency_success(data_service):
    """Test successful currency conversion."""
    amount = Decimal("100")

    # Mock FX client
    mock_rate = FxRate("USD", "EUR", Decimal("0.85"), datetime.now(timezone.utc))

    with patch('app.services.data_service.fx_client') as mock_client:
        mock_client.get_rate = AsyncMock(return_value=mock_rate)

        converted, source = await data_service.convert_currency(amount, "USD", "EUR")

        assert converted == Decimal("85.0")
        assert source == "fx_service"


@pytest.mark.asyncio
async def test_convert_currency_fallback(data_service):
    """Test currency conversion with fallback rate."""
    amount = Decimal("100")

    # Mock FX client with fallback rate
    mock_rate = FxRate("USD", "EUR", Decimal("0.85"), datetime.now(timezone.utc), source="fallback")

    with patch('app.services.data_service.fx_client') as mock_client:
        mock_client.get_rate = AsyncMock(return_value=mock_rate)

        converted, source = await data_service.convert_currency(amount, "USD", "EUR")

        assert converted == Decimal("85.0")
        assert source == "fallback"


@pytest.mark.asyncio
async def test_convert_currency_unavailable(data_service):
    """Test currency conversion when no rate available."""
    amount = Decimal("100")

    with patch('app.services.data_service.fx_client') as mock_client:
        mock_client.get_rate = AsyncMock(return_value=None)

        converted, source = await data_service.convert_currency(amount, "USD", "EUR")

        assert converted is None
        assert source == "unavailable"


@pytest.mark.asyncio
async def test_get_symbols_metadata_success(data_service):
    """Test successful metadata retrieval."""
    symbols = ["AAPL.US", "MSFT.US"]

    # Mock metadata
    mock_metadata = {
        "AAPL.US": SymbolMeta("AAPL.US", "US", "stock", "USD", "Apple Inc."),
        "MSFT.US": SymbolMeta("MSFT.US", "US", "stock", "USD", "Microsoft Corp.")
    }

    with patch('app.services.data_service.market_data_client') as mock_client:
        mock_client.get_symbols_meta = AsyncMock(return_value=mock_metadata)

        metadata = await data_service.get_symbols_metadata(symbols)

        assert len(metadata) == 2
        assert metadata["AAPL.US"].name == "Apple Inc."
        assert metadata["MSFT.US"].name == "Microsoft Corp."


@pytest.mark.asyncio
async def test_get_symbols_metadata_fallback(data_service):
    """Test metadata retrieval with fallback to defaults."""
    symbols = ["AAPL.US"]

    with patch('app.services.data_service.market_data_client') as mock_client:
        # Service fails, use fallback
        mock_client.get_symbols_meta = AsyncMock(side_effect=Exception("Service unavailable"))
        mock_client._parse_symbol_defaults.return_value = SymbolMeta("AAPL.US", "US", "stock", "USD")

        metadata = await data_service.get_symbols_metadata(symbols)

        assert len(metadata) == 1
        assert metadata["AAPL.US"].market == "US"
        assert metadata["AAPL.US"].asset_class == "stock"


@pytest.mark.asyncio
async def test_enrich_positions_with_current_data(data_service, mock_positions):
    """Test position enrichment with current data."""
    # Mock quotes and metadata
    mock_quotes = {
        "AAPL.US": Quote("AAPL.US", Decimal("160.0"), "USD", datetime.now(timezone.utc)),
        "MSFT.US": Quote("MSFT.US", Decimal("320.0"), "USD", datetime.now(timezone.utc))
    }
    mock_freshness = {"AAPL.US": "real_time", "MSFT.US": "real_time"}

    mock_metadata = {
        "AAPL.US": SymbolMeta("AAPL.US", "US", "stock", "USD", "Apple Inc."),
        "MSFT.US": SymbolMeta("MSFT.US", "US", "stock", "USD", "Microsoft Corp.")
    }

    with patch.object(data_service, 'get_current_quotes') as mock_quotes_method, \
         patch.object(data_service, 'get_symbols_metadata') as mock_meta_method:

        mock_quotes_method.return_value = (mock_quotes, mock_freshness)
        mock_meta_method.return_value = mock_metadata

        enriched_positions, data_quality = await data_service.enrich_positions_with_current_data(mock_positions)

        assert len(enriched_positions) == 2

        # Check AAPL enrichment
        aapl_pos = next(p for p in enriched_positions if p["symbol"] == "AAPL.US")
        assert aapl_pos["current_price_ccy"] == Decimal("160.0")
        assert aapl_pos["current_value_ccy"] == Decimal("1600.0")  # 10 * 160
        assert aapl_pos["name"] == "Apple Inc."
        assert aapl_pos["asset_class"] == "stock"

        # Check data quality
        assert data_quality["AAPL.US"]["quote_freshness"] == "real_time"
        assert data_quality["AAPL.US"]["metadata_available"] is True


@pytest.mark.asyncio
async def test_get_portfolio_real_time_value(data_service, mock_positions):
    """Test real-time portfolio value calculation."""
    # Mock enriched positions
    enriched_positions = [
        {
            "symbol": "AAPL.US",
            "qty": Decimal("10"),
            "current_value_ccy": Decimal("1600.0"),
            "current_price_currency": "USD"
        },
        {
            "symbol": "MSFT.US",
            "qty": Decimal("5"),
            "current_value_ccy": Decimal("1600.0"),
            "current_price_currency": "USD"
        }
    ]

    data_quality = {
        "AAPL.US": {"quote_freshness": "real_time"},
        "MSFT.US": {"quote_freshness": "real_time"}
    }

    with patch.object(data_service, 'enrich_positions_with_current_data') as mock_enrich, \
         patch.object(data_service, 'convert_currency') as mock_convert:

        mock_enrich.return_value = (enriched_positions, data_quality)
        mock_convert.return_value = (Decimal("85.0"), "fx_service")  # Mock USD to EUR conversion

        total_value, quality_stats = await data_service.get_portfolio_real_time_value(mock_positions)

        assert total_value == Decimal("170.0")  # 2 * 85 EUR
        assert quality_stats["positions"] == 2
        assert quality_stats["real_time"] == 2
        assert quality_stats["cached"] == 0
        assert quality_stats["fallback"] == 0


@pytest.mark.asyncio
async def test_batch_convert_currency(data_service):
    """Test batch currency conversion."""
    conversions = [
        (Decimal("100"), "USD", "EUR"),
        (Decimal("200"), "GBP", "EUR")
    ]

    # Mock FX rates
    mock_rates = {
        ("USD", "EUR"): FxRate("USD", "EUR", Decimal("0.85"), datetime.now(timezone.utc)),
        ("GBP", "EUR"): FxRate("GBP", "EUR", Decimal("1.15"), datetime.now(timezone.utc))
    }

    with patch('app.services.data_service.fx_client') as mock_client:
        mock_client.get_rates = AsyncMock(return_value=mock_rates)
        mock_client._cache_key.side_effect = lambda x, y: (x, y)

        results = await data_service.batch_convert_currency(conversions)

        assert len(results) == 2
        assert results[0] == (Decimal("85.0"), "fx_service")  # 100 * 0.85
        assert results[1] == (Decimal("230.0"), "fx_service")  # 200 * 1.15


@pytest.mark.asyncio
async def test_health_check(data_service):
    """Test health check functionality."""
    with patch('app.services.data_service.fx_client') as mock_fx, \
         patch('app.services.data_service.market_data_client') as mock_md:

        mock_fx.health_check = AsyncMock(return_value=True)
        mock_fx.cache = {"test": "entry"}
        mock_md.health_check = AsyncMock(return_value=True)
        mock_md.get_cache_stats.return_value = {"quotes_cached": 5, "meta_cached": 3}

        health = await data_service.health_check()

        assert health["fx_service"]["healthy"] is True
        assert health["fx_service"]["cache_entries"] == 1
        assert health["market_data_service"]["healthy"] is True
        assert health["market_data_service"]["cache_stats"]["quotes_cached"] == 5
        assert health["overall_healthy"] is True


@pytest.mark.asyncio
async def test_clear_caches(data_service):
    """Test cache clearing functionality."""
    with patch('app.services.data_service.fx_client') as mock_fx, \
         patch('app.services.data_service.market_data_client') as mock_md:

        # Create a mock cache with a clear method
        mock_cache = MagicMock()
        mock_fx.cache = mock_cache
        mock_md.clear_cache = AsyncMock()

        await data_service.clear_caches()

        mock_cache.clear.assert_called_once()
        mock_md.clear_cache.assert_called_once()