"""
Tests for telegram_router to portfolio_core integration after fixes.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app


@pytest.fixture
def client():
    """Test client fixture."""
    return TestClient(app)


def test_portfolio_endpoint_with_user_context(client):
    """Test /portfolio endpoint with proper user context parameters."""
    # These are the parameters telegram_router should now send
    user_params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en"
    }

    response = client.get("/portfolio", params=user_params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "portfolio" in data["data"]


def test_cash_endpoint_with_user_context(client):
    """Test /cash endpoint with proper user context parameters."""
    user_params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en"
    }

    response = client.get("/cash", params=user_params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "cash_balance" in data["data"]


def test_buy_endpoint_correct_path(client):
    """Test /buy endpoint (not /tx/buy) works correctly."""
    params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en",
        "qty": 10,
        "symbol": "AAPL.US",
        "price_ccy": 150.0
    }

    response = client.post("/buy", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "tx" in data["data"]


def test_sell_endpoint_correct_path(client):
    """Test /sell endpoint (not /tx/sell) works correctly."""
    params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en",
        "qty": 5,
        "symbol": "AAPL.US",
        "price_ccy": 155.0
    }

    response = client.post("/sell", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "tx" in data["data"]


def test_tx_endpoint_with_limit_parameter(client):
    """Test /tx endpoint accepts 'limit' parameter (not 'n')."""
    params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en",
        "limit": 5  # telegram_router should now send this instead of 'n'
    }

    response = client.get("/tx", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "transactions" in data["data"]


def test_allocation_edit_with_individual_parameters(client):
    """Test /allocation_edit endpoint with individual percentage parameters."""
    params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en",
        "etf_pct": 60,    # telegram_router should now send these
        "stock_pct": 30,  # instead of a 'weights' array
        "crypto_pct": 10
    }

    response = client.post("/allocation_edit", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "targets" in data["data"]


def test_allocation_endpoint(client):
    """Test /allocation endpoint works."""
    params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en"
    }

    response = client.get("/allocation", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "allocation" in data["data"]


def test_add_position_endpoint(client):
    """Test /add endpoint works correctly."""
    params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en",
        "qty": 100,
        "symbol": "MSFT.US",
        "type": "stock"
    }

    response = client.post("/add", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "position" in data["data"]


def test_portfolio_snapshot_endpoint(client):
    """Test /portfolio_snapshot endpoint with period parameter."""
    params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en",
        "period": "d"
    }

    response = client.get("/portfolio_snapshot", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "snapshot" in data["data"]


def test_error_handling_missing_user_context(client):
    """Test endpoints handle missing user context gracefully."""
    # Test without user_id - should still work (user_id can be None)
    response = client.get("/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True


def test_parameter_validation(client):
    """Test parameter validation works correctly."""
    # Test invalid period parameter
    params = {
        "user_id": 12345,
        "first_name": "Test",
        "last_name": "User",
        "username": "testuser",
        "language_code": "en",
        "period": "invalid"  # Should be d|w|m|y
    }

    response = client.get("/portfolio_snapshot", params=params)
    assert response.status_code == 400  # Validation error (custom handler)


@pytest.mark.asyncio
async def test_full_workflow_simulation():
    """Test a full workflow that telegram_router would execute."""
    client = TestClient(app)

    user_context = {
        "user_id": 99999,
        "first_name": "Integration",
        "last_name": "Test",
        "username": "integration_test",
        "language_code": "en"
    }

    # 1. Check initial portfolio (should be empty)
    response = client.get("/portfolio", params=user_context)
    assert response.status_code == 200
    initial_portfolio = response.json()
    assert initial_portfolio["ok"] is True

    # 2. Add some cash
    cash_params = user_context.copy()
    cash_params["amount"] = 10000
    response = client.post("/cash_add", params=cash_params)
    assert response.status_code == 200

    # 3. Add a position
    add_params = user_context.copy()
    add_params.update({"qty": 10, "symbol": "NVDA.US", "type": "stock"})
    response = client.post("/add", params=add_params)
    assert response.status_code == 200

    # 4. Buy some shares
    buy_params = user_context.copy()
    buy_params.update({"qty": 5, "symbol": "NVDA.US", "price_ccy": 800})
    response = client.post("/buy", params=buy_params)
    assert response.status_code == 200

    # 5. Check updated portfolio
    response = client.get("/portfolio", params=user_context)
    assert response.status_code == 200
    updated_portfolio = response.json()
    assert updated_portfolio["ok"] is True

    # 6. Check transactions
    tx_params = user_context.copy()
    tx_params["limit"] = 10
    response = client.get("/tx", params=tx_params)
    assert response.status_code == 200
    transactions = response.json()
    assert transactions["ok"] is True

    # 7. Check allocation
    response = client.get("/allocation", params=user_context)
    assert response.status_code == 200
    allocation = response.json()
    assert allocation["ok"] is True

    # 8. Update allocation
    alloc_params = user_context.copy()
    alloc_params.update({"etf_pct": 50, "stock_pct": 40, "crypto_pct": 10})
    response = client.post("/allocation_edit", params=alloc_params)
    assert response.status_code == 200

    # All operations should have succeeded
    print("✅ Full integration workflow completed successfully!")