"""Test configuration and fixtures."""
import os
import sqlite3
import pytest
import pytest_asyncio
import aiosqlite
from decimal import Decimal
from datetime import datetime, timezone

from app.models import UserContext
from app.services.portfolio import PortfolioService
from app.services.analytics import AnalyticsService
from app.db_adapter import adapt_decimal, convert_decimal

# Register adapters
sqlite3.register_adapter(Decimal, adapt_decimal)
sqlite3.register_converter("DECIMAL", convert_decimal)


@pytest.fixture
def market_data_mock():
    """Set up market_data client with mock data."""
    from app.clients.market_data import market_data
    
    # Mock data with Decimal strings
    price_map = {
        "AAPL": ("175.50", "160.00", "0.91"),  # price_ccy, price_eur, fx_rate
        "MSFT": ("250.00", "227.50", "0.91"),
        "NVDA": ("400.00", "364.00", "0.91"),
        "SPY": ("400.00", "364.00", "0.91"),
        "BTC": ("30000.00", "27300.00", "0.91"),
        "GLD": ("180.00", "163.80", "0.91")
    }
    
    # Prepare mock data for each endpoint
    mock_data = {}
    
    # Quotes endpoint
    quotes = []
    for symbol, (price_ccy, price_eur, fx_rate) in price_map.items():
        quotes.append({
            "symbol": symbol,
            "price_ccy": price_ccy,
            "price_eur": price_eur,
            "currency": "USD",
            "fx_rate": fx_rate
        })
    mock_data["/quote"] = {"quotes": quotes}
    
    # Metadata endpoint
    asset_class_map = {
        "BTC": ("CRYPTO", "crypto"),
        "SPY": ("US", "etf"),
        "SXR8": ("XETRA", "etf"),
        "AAPL": ("US", "stock"),
        "MSFT": ("US", "stock"),
        "NVDA": ("US", "stock"),
        "GLD": ("US", "etf")
    }
    
    meta = {}
    for symbol, (market, asset_class) in asset_class_map.items():
        meta[symbol] = {
            "symbol": symbol,
            "market": market,
            "currency": "USD",
            "asset_class": asset_class
        }
    mock_data["/meta"] = meta
    
    # Performance endpoint
    perf = []
    for symbol, (_, price_eur, _) in price_map.items():
        perf.append({
            "symbol": symbol,
            "return_pct": "1.5",
            "value_change_eur": str(Decimal(price_eur) * Decimal("0.015"))  # 1.5%
        })
    mock_data["/performance"] = {"performance": perf}
    
    # Benchmark endpoint
    mock_data["/benchmarks"] = {
        "SPY": {"values": [{"date": "2025-09-15", "value": "100.00"}]},
        "GLD": {"values": [{"date": "2025-09-15", "value": "100.00"}]}
    }
    
    # Enable mock mode with prepared data
    market_data.enable_mock_mode(mock_data)
    yield market_data
    market_data.disable_mock_mode()


@pytest_asyncio.fixture(scope="session")
async def test_db_path(tmp_path_factory):
    """Create temporary test database path."""
    test_dir = tmp_path_factory.mktemp("data")
    return str(test_dir / "test.db")


@pytest_asyncio.fixture
async def override_settings(test_db_path):
    """Override settings with test values."""
    from app.settings import get_settings
    settings = get_settings(test_db_path)
    # Use mock URL for market data in tests
    settings.MARKET_DATA_URL = "http://localhost:8001"
    return settings


@pytest_asyncio.fixture
async def init_db(test_db_path, override_settings):
    """Initialize test database."""
    from app.db import SCHEMA
    async with aiosqlite.connect(
        test_db_path, 
        detect_types=sqlite3.PARSE_DECLTYPES
    ) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()
    return test_db_path


@pytest_asyncio.fixture
async def db(init_db):
    """Database connection fixture."""
    async with aiosqlite.connect(
        init_db,
        detect_types=sqlite3.PARSE_DECLTYPES
    ) as db:
        db.row_factory = aiosqlite.Row
        yield db


@pytest.fixture
def test_user():
    """Test user context."""
    return UserContext(
        user_id=12345,
        first_name="Test",
        last_name="User",
        username="testuser",
        language_code="en"
    )


@pytest_asyncio.fixture
async def portfolio_service(db, test_user):
    """Portfolio service instance."""
    return PortfolioService(db, test_user)


@pytest_asyncio.fixture
async def portfolio_service(db, test_user, market_data_mock):
    """Portfolio service instance."""
    return PortfolioService(db, test_user)


@pytest_asyncio.fixture
async def analytics_service(db, test_user):
    """Analytics service instance."""
    return AnalyticsService(db, test_user)