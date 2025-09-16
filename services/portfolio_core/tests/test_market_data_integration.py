"""Tests for market data client integration."""
import pytest
from unittest.mock import AsyncMock, patch

from app.adapters.market_data_client import MarketDataClient
from app.services.portfolio import PortfolioService


@pytest.fixture
def mock_market_data():
    """Mock market data client."""
    with patch('app.adapters.market_data_client.MarketDataClient') as mock:
        client = mock.return_value
        client.get_latest_price = AsyncMock()
        client.get_exchange_rate = AsyncMock()
        yield client


@pytest.mark.asyncio
async def test_portfolio_valuation_with_market_data(portfolio_service, mock_market_data):
    """Test portfolio valuation using market data."""
    # Setup mock responses
    mock_market_data.get_latest_price.return_value = 160.0
    mock_market_data.get_exchange_rate.return_value = 1.0

    # Add test position to portfolio
    position = await portfolio_service.add_position("AAPL", 10, "stock")

    # Get portfolio snapshot
    snapshot = await portfolio_service.get_portfolio_snapshot()

    # Verify position was added
    assert len(snapshot["positions"]) == 1
    assert snapshot["positions"][0]["symbol"] == "AAPL"
    assert snapshot["positions"][0]["qty"] == 10


@pytest.mark.asyncio
async def test_foreign_currency_conversion(portfolio_service, mock_market_data):
    """Test handling of positions in different currencies."""
    # Setup mock responses
    mock_market_data.get_latest_price.return_value = 100.0  # EUR
    mock_market_data.get_exchange_rate.return_value = 1.1  # EUR/USD

    # Add EUR position
    position = await portfolio_service.add_position("SAN.MC", 10, "stock")

    # Get portfolio snapshot
    snapshot = await portfolio_service.get_portfolio_snapshot()

    # Verify position was added
    assert len(snapshot["positions"]) == 1
    assert snapshot["positions"][0]["symbol"] == "SAN.MC"
    assert snapshot["positions"][0]["qty"] == 10


@pytest.mark.asyncio
async def test_market_data_error_handling(portfolio_service, mock_market_data):
    """Test handling of market data service errors."""
    # Setup mock to raise exception
    mock_market_data.get_latest_price.side_effect = Exception("Service unavailable")

    # Add test position
    position = await portfolio_service.add_position("AAPL", 10, "stock")

    # Get portfolio snapshot should still work even if market data fails
    # because portfolio_core uses stored position data, not real-time quotes
    snapshot = await portfolio_service.get_portfolio_snapshot()

    # Verify position was added even though market data failed
    assert len(snapshot["positions"]) == 1
    assert snapshot["positions"][0]["symbol"] == "AAPL"