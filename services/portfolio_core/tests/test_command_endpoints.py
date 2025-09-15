"""
Tests for portfolio command endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from decimal import Decimal

from app.main import app
from app.db import init_db


@pytest.fixture
def client():
    """Test client fixture with database initialization."""
    return TestClient(app)


@pytest.fixture
def mock_user_params():
    """Mock user parameters for requests."""
    return {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en"
    }


def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["status"] == "healthy"


def test_auth_telegram_redirect(client):
    """Test telegram auth redirect."""
    response = client.post("/auth/telegram")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "market_data service" in data["error"]["message"]


def test_portfolio_endpoint(client, mock_user_params):
    """Test /portfolio endpoint."""
    response = client.get("/portfolio", params=mock_user_params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "portfolio" in data["data"]


def test_cash_endpoint(client, mock_user_params):
    """Test /cash endpoint."""
    response = client.get("/cash", params=mock_user_params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "cash_balance" in data["data"]


def test_add_position_endpoint(client, mock_user_params):
    """Test /add endpoint."""
    params = mock_user_params.copy()
    params.update({
        "qty": 10,
        "symbol": "AAPL.US",
        "type": "stock"
    })

    response = client.post("/add", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "position" in data["data"]


def test_cash_add_endpoint(client, mock_user_params):
    """Test /cash_add endpoint."""
    params = mock_user_params.copy()
    params["amount"] = 1000

    response = client.post("/cash_add", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "cash_balance" in data["data"]


def test_buy_endpoint(client, mock_user_params):
    """Test /buy endpoint."""
    params = mock_user_params.copy()
    params.update({
        "qty": 5,
        "symbol": "MSFT.US",
        "price_ccy": 300
    })

    response = client.post("/buy", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "tx" in data["data"]


def test_transactions_endpoint(client, mock_user_params):
    """Test /tx endpoint."""
    params = mock_user_params.copy()
    params["limit"] = 5

    response = client.get("/tx", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "transactions" in data["data"]


def test_portfolio_snapshot_endpoint(client, mock_user_params):
    """Test /portfolio_snapshot endpoint."""
    params = mock_user_params.copy()
    params["period"] = "d"

    response = client.get("/portfolio_snapshot", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "snapshot" in data["data"]


def test_portfolio_summary_endpoint(client, mock_user_params):
    """Test /portfolio_summary endpoint."""
    params = mock_user_params.copy()
    params["period"] = "w"

    response = client.get("/portfolio_summary", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "summary" in data["data"]


def test_allocation_endpoint(client, mock_user_params):
    """Test /allocation endpoint."""
    response = client.get("/allocation", params=mock_user_params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "allocation" in data["data"]


def test_allocation_edit_endpoint(client, mock_user_params):
    """Test /allocation_edit endpoint."""
    params = mock_user_params.copy()
    params.update({
        "etf_pct": 50,
        "stock_pct": 40,
        "crypto_pct": 10
    })

    response = client.post("/allocation_edit", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "targets" in data["data"]


def test_help_endpoint(client, mock_user_params):
    """Test /help endpoint."""
    response = client.get("/help", params=mock_user_params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "help" in data["data"]
    assert isinstance(data["data"]["help"], list)


def test_invalid_period(client, mock_user_params):
    """Test invalid period parameter."""
    params = mock_user_params.copy()
    params["period"] = "invalid"

    response = client.get("/portfolio_snapshot", params=params)
    assert response.status_code == 422  # Validation error


def test_missing_user_id():
    """Test missing user_id parameter."""
    client = TestClient(app)
    response = client.get("/portfolio")
    # Should still work with None user_id, just return empty portfolio
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_time_weighted_return_calculation():
    """Test TWR calculation logic."""
    from app.services.analytics import AnalyticsService
    from app.models import UserContext
    from app.db import open_db

    user_context = UserContext(user_id=12345, first_name="Test", last_name="User")

    async with await open_db() as conn:
        analytics = AnalyticsService(conn, user_context)

        # Mock snapshots and flows
        snapshots = [
            {"date": "2023-01-01", "value_eur": 10000},
            {"date": "2023-01-02", "value_eur": 10200},
            {"date": "2023-01-03", "value_eur": 10100},
        ]

        flows = [
            {"date": "2023-01-02", "amount_eur": 0},  # No flows
        ]

        from datetime import date
        twr_pct, daily_returns = await analytics.calculate_twr(
            date(2023, 1, 1), date(2023, 1, 3), snapshots, flows
        )

        # TWR should be calculated correctly
        assert isinstance(twr_pct, Decimal)
        assert len(daily_returns) > 0


@pytest.mark.asyncio
async def test_bucket_boundaries():
    """Test bucket boundary calculation."""
    from app.services.analytics import AnalyticsService
    from app.models import UserContext
    from app.db import open_db
    from datetime import date

    user_context = UserContext(user_id=12345, first_name="Test", last_name="User")

    async with await open_db() as conn:
        analytics = AnalyticsService(conn, user_context)

        # Test different period boundaries
        ref_date = date(2023, 6, 15)  # A Thursday

        # Daily boundaries
        d_boundaries = analytics._get_bucket_boundaries("d", ref_date)
        assert len(d_boundaries) == 1
        assert d_boundaries[0] == ref_date

        # Weekly boundaries
        w_boundaries = analytics._get_bucket_boundaries("w", ref_date)
        assert len(w_boundaries) == 7

        # Monthly boundaries (4 weekly Friday closes)
        m_boundaries = analytics._get_bucket_boundaries("m", ref_date)
        assert len(m_boundaries) == 4

        # Yearly boundaries (YTD monthly)
        y_boundaries = analytics._get_bucket_boundaries("y", ref_date)
        assert len(y_boundaries) == 6  # Jan through Jun