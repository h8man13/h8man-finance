import os
import sys
import warnings
import asyncio
import types
import pytest
from starlette.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _env_setup(tmp_path_factory):
    # Isolated data dirs
    data_dir = tmp_path_factory.mktemp("tg_router_data")
    os.environ.setdefault("IDEMPOTENCY_PATH", str(data_dir / "idempotency.json"))
    os.environ.setdefault("SESSIONS_DIR", str(data_dir / "sessions"))

    # Router operating mode and secrets
    os.environ.setdefault("TELEGRAM_MODE", "webhook")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:testtoken")
    os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "whsec_test")
    os.environ.setdefault("ROUTER_OWNER_IDS", "42")

    # Point registry/copies/ranking to this repo's config files
    base = os.path.abspath("services/telegram_router")
    os.environ.setdefault("REGISTRY_PATH", os.path.join(base, "config", "commands.json"))
    os.environ.setdefault("COPIES_PATH", os.path.join(base, "config", "router_copies.yaml"))
    os.environ.setdefault("RANKING_PATH", os.path.join(base, "config", "help_ranking.yaml"))

    # Avoid flaky warnings in test output
    warnings.filterwarnings(
        "ignore",
        message=r"Please use `import python_multipart` instead.",
        category=PendingDeprecationWarning,
        module=r"starlette\.formparsers",
    )


@pytest.fixture(scope="session")
def app():
    # Allow importing the service-local package
    sys.path.insert(0, os.path.abspath("services/telegram_router"))
    # Avoid collision with market_data package name 'app' by clearing any cached modules
    for k in list(sys.modules.keys()):
        if k == "app" or k.startswith("app."):
            sys.modules.pop(k, None)
    from app.app import app as fastapi_app  # type: ignore
    return fastapi_app


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def capture_telegram(monkeypatch):
    """Capture outgoing Telegram messages to avoid network and assert content."""
    sent = []

    async def _fake_send(token: str, chat_id: int, text: str, parse_mode: str = "MarkdownV2"):
        sent.append({"token": token, "chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    # Patch the symbol used in handlers
    import app.app as appmod  # type: ignore
    monkeypatch.setattr(appmod, "send_telegram_message", _fake_send)
    return sent


# Ensure Python can import the router service package regardless of test import order
@pytest.fixture(scope="session", autouse=True)
def _path_setup():
    sys.path.insert(0, os.path.abspath("services/telegram_router"))
    # Ensure we import the router's app package, not market_data's
    for k in list(sys.modules.keys()):
        if k == "app" or k.startswith("app."):
            sys.modules.pop(k, None)
    yield
