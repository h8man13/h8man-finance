"""
Integration tests for the new architecture with adapters and admin endpoints.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.main import app
from app.services.data_service import DataService
from app.adapters.fx_client import FxRate
from app.adapters.market_data_client import Quote, SymbolMeta


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


@pytest.fixture
def mock_user_params():
    """Mock user parameters."""
    return {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en"
    }


def test_full_portfolio_workflow_with_adapters(client, mock_user_params):
    """Test full portfolio workflow using adapters."""
    # Mock the adapter responses
    with patch('app.adapters.fx_client') as mock_fx, \
         patch('app.adapters.market_data_client') as mock_md:

        # Setup FX mock
        mock_fx.get_rate.return_value = FxRate(
            "USD", "EUR", Decimal("0.85"), datetime.now(timezone.utc)
        )
        mock_fx.health_check.return_value = True
        mock_fx.cache = {}

        # Setup market data mock
        mock_md.get_symbol_meta.return_value = SymbolMeta(
            "AAPL.US", "US", "stock", "USD", "Apple Inc."
        )
        mock_md.get_quote.return_value = Quote(
            "AAPL.US", Decimal("150.0"), "USD", datetime.now(timezone.utc)
        )
        mock_md.health_check.return_value = True
        mock_md.get_cache_stats.return_value = {
            "quotes_cached": 1,
            "meta_cached": 1,
            "quotes_valid": 1,
            "meta_valid": 1
        }

        # 1. Check initial portfolio (should be empty)
        response = client.get("/portfolio", params=mock_user_params)
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

        # 2. Add some cash
        params = mock_user_params.copy()
        params["amount"] = 1000
        response = client.post("/cash_add", params=params)
        assert response.status_code == 200

        # 3. Add a position
        params = mock_user_params.copy()
        params.update({
            "qty": 10,
            "symbol": "AAPL.US",
            "type": "stock"
        })
        response = client.post("/add", params=params)
        assert response.status_code == 200

        # 4. Buy some shares
        params = mock_user_params.copy()
        params.update({
            "qty": 5,
            "symbol": "AAPL.US",
            "price_ccy": 150
        })
        response = client.post("/buy", params=params)
        assert response.status_code == 200

        # 5. Check updated portfolio
        response = client.get("/portfolio", params=mock_user_params)
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["data"]["portfolio"]["positions"]) > 0

        # 6. Get portfolio analytics
        params = mock_user_params.copy()
        params["period"] = "d"
        response = client.get("/portfolio_snapshot", params=params)
        assert response.status_code == 200

        # 7. Check allocation
        response = client.get("/allocation", params=mock_user_params)
        assert response.status_code == 200


def test_admin_endpoints_integration(client):
    """Test admin endpoints work together."""
    with patch('app.api.fx_client') as mock_fx, \
         patch('app.api.market_data_client') as mock_md:

        # Setup mocks
        mock_fx.health_check.return_value = True
        mock_fx.cache = {}
        mock_md.health_check.return_value = True
        mock_md.get_cache_stats.return_value = {
            "quotes_cached": 0,
            "meta_cached": 0,
            "quotes_valid": 0,
            "meta_valid": 0
        }

        # 1. Health check
        response = client.get("/admin/health")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "database" in data["data"]
        assert "fx_service" in data["data"]
        assert "market_data_service" in data["data"]

        # 2. Check snapshot status (initially empty)
        response = client.get("/admin/snapshots/status")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["total_users"] == 0

        # 3. Run snapshots (no users yet)
        response = client.post("/admin/snapshots/run")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["processed_users"] == 0

        # 4. Cleanup snapshots
        response = client.delete("/admin/snapshots/cleanup?days_to_keep=30")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["deleted_snapshots"] == 0


@pytest.mark.asyncio
async def test_data_service_integration(user_context):
    """Test the data service with mocked adapters."""
    with patch('app.services.data_service.fx_client') as mock_fx, \
         patch('app.services.data_service.market_data_client') as mock_md:

        # Setup mocks
        mock_fx.get_rate.return_value = FxRate(
            "USD", "EUR", Decimal("0.85"), datetime.now(timezone.utc)
        )
        mock_fx.get_rates.return_value = {
            ("USD", "EUR"): FxRate("USD", "EUR", Decimal("0.85"), datetime.now(timezone.utc))
        }
        mock_fx._cache_key.return_value = ("USD", "EUR")

        mock_md.get_quotes.return_value = {
            "AAPL.US": Quote("AAPL.US", Decimal("150.0"), "USD", datetime.now(timezone.utc))
        }
        mock_md.get_symbols_meta.return_value = {
            "AAPL.US": SymbolMeta("AAPL.US", "US", "stock", "USD", "Apple Inc.")
        }

        # Create data service
        data_service = DataService(user_context)

        # Test quote retrieval
        quotes, freshness = await data_service.get_current_quotes(["AAPL.US"])
        assert len(quotes) == 1
        assert "AAPL.US" in quotes
        assert freshness["AAPL.US"] == "real_time"

        # Test metadata retrieval
        metadata = await data_service.get_symbols_metadata(["AAPL.US"])
        assert len(metadata) == 1
        assert metadata["AAPL.US"].name == "Apple Inc."

        # Test currency conversion
        converted, source = await data_service.convert_currency(
            Decimal("100"), "USD", "EUR"
        )
        assert converted == Decimal("85.0")
        assert source == "fx_service"

        # Test portfolio value calculation
        mock_positions = [
            {
                "symbol": "AAPL.US",
                "qty": Decimal("10"),
                "avg_cost_eur": Decimal("127.5"),
                "ccy": "USD"
            }
        ]

        enriched_positions, quality = await data_service.enrich_positions_with_current_data(mock_positions)
        assert len(enriched_positions) == 1
        assert enriched_positions[0]["current_price_ccy"] == Decimal("150.0")
        assert quality["AAPL.US"]["quote_freshness"] == "real_time"


def test_error_handling_with_adapters(client, mock_user_params):
    """Test error handling when adapters fail."""
    with patch('app.adapters.fx_client') as mock_fx, \
         patch('app.adapters.market_data_client') as mock_md:

        # Setup failing adapters
        mock_fx.get_rate.return_value = None
        mock_fx.health_check.return_value = False
        mock_md.get_quote.return_value = None
        mock_md.health_check.return_value = False
        mock_md.get_cache_stats.return_value = {
            "quotes_cached": 0,
            "meta_cached": 0,
            "quotes_valid": 0,
            "meta_valid": 0
        }

        # Endpoints should still work with graceful degradation
        response = client.get("/portfolio", params=mock_user_params)
        assert response.status_code == 200

        # Admin health should show service issues
        response = client.get("/admin/health")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        # FX and market data services should be marked as unhealthy
        assert data["data"]["fx_service"]["healthy"] is False
        assert data["data"]["market_data_service"]["healthy"] is False


def test_cron_job_simulation(client):
    """Test simulating the cron job workflow."""
    with patch('app.api.fx_client') as mock_fx, \
         patch('app.api.market_data_client') as mock_md:

        # Setup healthy mocks
        mock_fx.health_check.return_value = True
        mock_fx.cache = {}
        mock_md.health_check.return_value = True
        mock_md.get_cache_stats.return_value = {
            "quotes_cached": 0,
            "meta_cached": 0,
            "quotes_valid": 0,
            "meta_valid": 0
        }

        # Simulate cron job workflow:
        # 1. Health check
        response = client.get("/admin/health")
        assert response.status_code == 200
        assert response.json()["ok"] is True

        # 2. Get status before
        response = client.get("/admin/snapshots/status")
        assert response.status_code == 200
        pre_status = response.json()["data"]

        # 3. Run snapshots
        response = client.post("/admin/snapshots/run")
        assert response.status_code == 200
        run_result = response.json()["data"]

        # 4. Cleanup old snapshots
        response = client.delete("/admin/snapshots/cleanup?days_to_keep=90")
        assert response.status_code == 200
        cleanup_result = response.json()["data"]

        # 5. Get status after
        response = client.get("/admin/snapshots/status")
        assert response.status_code == 200
        post_status = response.json()["data"]

        # Verify the workflow completed
        assert "processed_users" in run_result
        assert "deleted_snapshots" in cleanup_result
        assert pre_status["total_users"] == post_status["total_users"]


@pytest.mark.asyncio
async def test_batch_operations(user_context):
    """Test batch operations in adapters."""
    with patch('app.services.data_service.fx_client') as mock_fx, \
         patch('app.services.data_service.market_data_client') as mock_md:

        # Setup batch mocks
        mock_fx.get_rates.return_value = {
            ("USD", "EUR"): FxRate("USD", "EUR", Decimal("0.85"), datetime.now(timezone.utc)),
            ("GBP", "EUR"): FxRate("GBP", "EUR", Decimal("1.15"), datetime.now(timezone.utc))
        }
        mock_fx._cache_key.side_effect = lambda x, y: (x, y)

        mock_md.get_quotes.return_value = {
            "AAPL.US": Quote("AAPL.US", Decimal("150.0"), "USD", datetime.now(timezone.utc)),
            "MSFT.US": Quote("MSFT.US", Decimal("300.0"), "USD", datetime.now(timezone.utc))
        }

        data_service = DataService(user_context)

        # Test batch currency conversion
        conversions = [
            (Decimal("100"), "USD", "EUR"),
            (Decimal("200"), "GBP", "EUR")
        ]
        results = await data_service.batch_convert_currency(conversions)

        assert len(results) == 2
        assert results[0] == (Decimal("85.0"), "fx_service")
        assert results[1] == (Decimal("230.0"), "fx_service")

        # Test batch quote retrieval
        quotes, freshness = await data_service.get_current_quotes(["AAPL.US", "MSFT.US"])
        assert len(quotes) == 2
        assert "AAPL.US" in quotes
        assert "MSFT.US" in quotes