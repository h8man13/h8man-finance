"""Tests for analytics service."""
import pytest
from datetime import datetime, timezone, timedelta

from app.services.analytics import AnalyticsService
from app.models import PortfolioSnapshot, PositionPerformance


@pytest.mark.asyncio
async def test_calculate_portfolio_performance(analytics_service, portfolio_service):
    """Test portfolio performance calculation."""
    # Setup test portfolio with positions
    portfolio = await portfolio_service.create_portfolio("Test", "Test desc", "USD")
    
    position1 = await portfolio_service.add_position(
        portfolio.id, "AAPL", 10, 150.0, "USD"
    )
    position2 = await portfolio_service.add_position(
        portfolio.id, "MSFT", 20, 200.0, "USD"
    )
    
    # Add transactions
    date = datetime.now(timezone.utc)
    await portfolio_service.add_transaction(
        portfolio.id, position1.id, 10, 150.0, date - timedelta(days=30)
    )
    await portfolio_service.add_transaction(
        portfolio.id, position2.id, 20, 200.0, date - timedelta(days=30)
    )
    
    # Calculate performance
    start_date = date - timedelta(days=30)
    end_date = date
    
    performance = await analytics_service.calculate_portfolio_performance(
        portfolio.id, start_date, end_date
    )
    
    assert performance.portfolio_id == portfolio.id
    assert performance.start_date.replace(microsecond=0) == start_date.replace(microsecond=0)
    assert performance.end_date.replace(microsecond=0) == end_date.replace(microsecond=0)
    assert isinstance(performance.return_pct, float)


@pytest.mark.asyncio
async def test_get_position_performance(analytics_service, portfolio_service):
    """Test position performance calculation."""
    # Setup test portfolio with position
    portfolio = await portfolio_service.create_portfolio("Test", "Test desc", "USD")
    position = await portfolio_service.add_position(
        portfolio.id, "AAPL", 10, 150.0, "USD"
    )
    
    # Add transaction
    date = datetime.now(timezone.utc)
    await portfolio_service.add_transaction(
        portfolio.id, position.id, 10, 150.0, date - timedelta(days=30)
    )
    
    # Get performance
    performance = await analytics_service.get_position_performance(portfolio.id, position.id)
    
    assert performance.position_id == position.id
    assert performance.symbol == position.symbol
    assert isinstance(performance.unrealized_gain, float)
    assert isinstance(performance.total_return_pct, float)


@pytest.mark.asyncio
async def test_create_portfolio_snapshot(analytics_service, portfolio_service):
    """Test portfolio snapshot creation."""
    # Setup test portfolio
    portfolio = await portfolio_service.create_portfolio("Test", "Test desc", "USD")
    position = await portfolio_service.add_position(
        portfolio.id, "AAPL", 10, 150.0, "USD"
    )
    
    # Create snapshot
    date = datetime.now(timezone.utc)
    snapshot = await analytics_service.create_portfolio_snapshot(portfolio.id, date)
    
    assert snapshot.portfolio_id == portfolio.id
    assert snapshot.date.replace(microsecond=0) == date.replace(microsecond=0)
    assert isinstance(snapshot.total_value, float)
    assert isinstance(snapshot.cash_value, float)
    assert isinstance(snapshot.invested_value, float)