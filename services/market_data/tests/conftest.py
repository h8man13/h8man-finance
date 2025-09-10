import os
import sys
import warnings
import pytest
from starlette.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _env_setup(tmp_path_factory):
    # Ensure settings pick test env and an isolated DB
    os.environ.setdefault("ENV", "test")
    os.environ.setdefault("EODHD_API_TOKEN", "test-token")
    os.environ.setdefault("DB_PATH", str(tmp_path_factory.mktemp("md_db") / "cache.db"))
    # Relax CORS to regex (default in app), but make it explicit for clarity
    os.environ.setdefault("CORS_ALLOW_ORIGINS", "")
    os.environ.setdefault("CORS_ALLOW_ORIGIN_REGEX", r"https?://.*")
    # Use UTC tz to avoid OS tzdata dependency in tests
    os.environ.setdefault("TZ", "UTC")
    # FX base URL not used (we mock), but set a placeholder
    os.environ.setdefault("FX_BASE_URL", "http://fx:8000")

    # Silence Starlette PendingDeprecation about multipart import (upstream issue)
    warnings.filterwarnings(
        "ignore",
        message=r"Please use `import python_multipart` instead.",
        category=PendingDeprecationWarning,
        module=r"starlette\.formparsers",
    )


@pytest.fixture(scope="session")
def app():
    # Allow importing the service-local package
    sys.path.insert(0, os.path.abspath("services/market_data"))
    from app.main import app as fastapi_app  # type: ignore
    return fastapi_app


@pytest.fixture()
def client(app):
    return TestClient(app)
