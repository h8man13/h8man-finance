"""Tests for market data client integration."""
import pytest
from unittest.mock import AsyncMock, patch

from app.clients.market_data import MarketDataClient
from app.services.portfolio import PortfolioService


@pytest.fixture
def mock_market_data():
    """Mock market data client."""
    with patch('app.clients.market_data.MarketDataClient') as mock:
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
    
    # Create test portfolio with position
    portfolio = await portfolio_service.create_portfolio("Test", "Test desc", "USD")
    position = await portfolio_service.add_position(
        portfolio.id, "AAPL", 10, 150.0, "USD"
    )
    
    # Get portfolio value
    value = await portfolio_service.get_portfolio_value(portfolio.id)
    
    # Verify market data client was called
    mock_market_data.get_latest_price.assert_called_once_with("AAPL")
    
    # Verify calculations
    expected_value = 10 * 160.0  # quantity * current_price
    assert value == expected_value


@pytest.mark.asyncio
async def test_foreign_currency_conversion(portfolio_service, mock_market_data):
    """Test handling of positions in different currencies."""
    # Setup mock responses
    mock_market_data.get_latest_price.return_value = 100.0  # EUR
    mock_market_data.get_exchange_rate.return_value = 1.1  # EUR/USD
    
    # Create USD portfolio with EUR position
    portfolio = await portfolio_service.create_portfolio("Test", "Test desc", "USD")
    position = await portfolio_service.add_position(
        portfolio.id, "SAN.MC", 10, 90.0, "EUR"
    )
    
    # Get portfolio value (should be converted to USD)
    value = await portfolio_service.get_portfolio_value(portfolio.id)
    
    # Verify market data client calls
    mock_market_data.get_latest_price.assert_called_once_with("SAN.MC")
    mock_market_data.get_exchange_rate.assert_called_once_with("EUR", "USD")
    
    # Verify calculations
    expected_value = 10 * 100.0 * 1.1  # quantity * price * exchange_rate
    assert value == expected_value


@pytest.mark.asyncio
async def test_market_data_error_handling(portfolio_service, mock_market_data):
    """Test handling of market data service errors."""
    # Setup mock to raise exception
    mock_market_data.get_latest_price.side_effect = Exception("Service unavailable")
    
    # Create test portfolio with position
    portfolio = await portfolio_service.create_portfolio("Test", "Test desc", "USD")
    position = await portfolio_service.add_position(
        portfolio.id, "AAPL", 10, 150.0, "USD"
    )
    
    # Verify error handling
    with pytest.raises(Exception) as exc_info:
        await portfolio_service.get_portfolio_value(portfolio.id)
    
    assert "Service unavailable" in str(exc_info.value)