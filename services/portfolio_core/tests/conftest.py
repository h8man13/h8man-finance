from __future__ import annotations

try:
    from respx.models import CallList
except Exception:  # pragma: no cover - respx may be unavailable outside tests
    CallList = None

if CallList is not None:
    def _reset(self):
        self._calls.clear()
        self._index = 0
    CallList.reset = _reset



import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.settings import settings
from app import db
from app.clients import market_data_client


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def _test_db(tmp_path: Path):
    db_path = tmp_path / "portfolio.db"
    settings.DB_PATH = str(db_path)
    await db.init_db(str(db_path))
    settings.MARKET_DATA_BASE_URL = "http://market-data.test"
    market_data_client._base_url = settings.MARKET_DATA_BASE_URL.rstrip("/")
    market_data_client.clear_cache()
    yield
    await market_data_client.close()


@pytest_asyncio.fixture
async def async_client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def conn():
    connection = await db.open_db(settings.DB_PATH)
    try:
        yield connection
    finally:
        await connection.close()



