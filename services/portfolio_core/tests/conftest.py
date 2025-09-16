"""Test configuration and fixtures."""
import os
import tempfile
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

# Set test environment variables before imports
os.environ.setdefault("DB_PATH", "/tmp/test_portfolio.db")

from app.db import init_db, open_db
from app.models import UserContext
from app.services.portfolio import PortfolioService
from app.services.analytics import AnalyticsService


# Removed custom event_loop fixture as it's deprecated in pytest-asyncio
# Tests now use the default pytest-asyncio event loop


@pytest.fixture
async def test_db():
    """Create a temporary test database."""
    # Create temporary file for test database
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    try:
        # Initialize database with test path
        await init_db(path)
        yield path
    finally:
        # Clean up
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
async def db_connection(test_db):
    """Database connection fixture."""
    conn = await open_db(test_db)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
def user_context():
    """Test user context fixture."""
    return UserContext(
        user_id=12345,
        first_name="Test",
        last_name="User",
        username="testuser",
        language_code="en"
    )


@pytest.fixture
def portfolio_service(db_connection, user_context):
    """Portfolio service fixture."""
    return PortfolioService(db_connection, user_context)


@pytest.fixture
def analytics_service(db_connection, user_context):
    """Analytics service fixture."""
    return AnalyticsService(db_connection, user_context)


@pytest.fixture
def mock_adapters():
    """Mock external service adapters."""
    with patch('app.adapters.fx_client') as mock_fx, \
         patch('app.adapters.market_data_client') as mock_md:

        # Setup default mock responses
        mock_fx.health_check.return_value = True
        mock_fx.cache = {}
        mock_fx.get_rate.return_value = None
        mock_fx.get_rates.return_value = {}

        mock_md.health_check.return_value = True
        mock_md.get_cache_stats.return_value = {
            "quotes_cached": 0,
            "meta_cached": 0,
            "quotes_valid": 0,
            "meta_valid": 0
        }
        mock_md.get_quote.return_value = None
        mock_md.get_quotes.return_value = {}
        mock_md.get_symbol_meta.return_value = None
        mock_md.get_symbols_meta.return_value = {}
        mock_md.clear_cache = AsyncMock()

        yield {"fx": mock_fx, "market_data": mock_md}