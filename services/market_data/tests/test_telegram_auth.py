import os
import sys
import json
import hmac
import hashlib
import urllib.parse
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient


def _hmac_webappdata_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def _data_check_string_sorted(pairs: dict) -> str:
    filtered = {k: v for k, v in pairs.items() if k not in ("hash", "signature")}
    return "\n".join(f"{k}={filtered[k]}" for k in sorted(filtered.keys()))


def make_init_data(bot_token: str, pairs: dict, hash_on: str = "sorted") -> str:
    raw_qs = urllib.parse.urlencode(pairs, doseq=False)
    key = _hmac_webappdata_key(bot_token)
    if hash_on == "sorted":
        dcs = _data_check_string_sorted(pairs)
    elif hash_on == "original":
        parts = []
        for part in raw_qs.split("&"):
            if not part:
                continue
            k, v = (part.split("=", 1) + [""])[:2]
            if k in ("hash", "signature"):
                continue
            parts.append(f"{k}={v}")
        dcs = "\n".join(parts)
    else:
        raise ValueError("hash_on must be 'sorted' or 'original'")
    sig_hex = hmac.new(key, msg=dcs.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()
    sep = "&" if raw_qs else ""
    return f"{raw_qs}{sep}hash={sig_hex}"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    # Set env BEFORE importing the app
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:testtoken")
    os.environ.setdefault("INITDATA_MAX_AGE_SEC", "3600")
    os.environ.setdefault("DB_PATH", str(tmp_path_factory.mktemp("md_db") / "cache.db"))

    # Ensure Python can import the service-local 'app' package
    sys.path.insert(0, os.path.abspath("services/market_data"))

    # Import app after env is set
    from app.main import app  # type: ignore
    return TestClient(app)


def test_auth_header_valid_sorted(client):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    user = {"id": 42, "first_name": "Ada", "username": "ada"}
    now = int(datetime.now(timezone.utc).timestamp())
    pairs = {"query_id": "AAHxyz", "user": json.dumps(user, separators=(",", ":")), "auth_date": str(now)}
    init_data = make_init_data(bot_token, pairs, hash_on="sorted")
    r = client.post("/auth/telegram", headers={"Telegram-Init-Data": init_data})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    assert js["data"]["user_id"] == 42


def test_auth_authorization_tma_header(client):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    user = {"id": 42, "first_name": "Ada", "username": "ada"}
    now = int(datetime.now(timezone.utc).timestamp())
    pairs = {"query_id": "AAHxyz", "user": json.dumps(user, separators=(",", ":")), "auth_date": str(now)}
    init_data = make_init_data(bot_token, pairs, hash_on="sorted")
    r = client.post("/auth/telegram", headers={"Authorization": f"tma {init_data}"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_auth_json_body(client):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    user = {"id": 42, "first_name": "Ada", "username": "ada"}
    now = int(datetime.now(timezone.utc).timestamp())
    pairs = {"query_id": "AAHxyz", "user": json.dumps(user, separators=(",", ":")), "auth_date": str(now)}
    init_data = make_init_data(bot_token, pairs, hash_on="sorted")
    r = client.post("/auth/telegram", json={"initData": init_data})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_auth_tampered_invalid(client):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    user = {"id": 42, "first_name": "Ada", "username": "ada"}
    now = int(datetime.now(timezone.utc).timestamp())
    pairs = {"query_id": "AAHxyz", "user": json.dumps(user, separators=(",", ":")), "auth_date": str(now)}
    init_data = make_init_data(bot_token, pairs, hash_on="sorted")
    tampered = init_data.replace(f"auth_date={now}", f"auth_date={now+1}")
    r = client.post("/auth/telegram", headers={"Telegram-Init-Data": tampered})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is False
    assert js["error"]["code"] == "BAD_INPUT"


def test_auth_stale_beyond_max_age(client, monkeypatch):
    # Set max age to 5s and use an older auth_date
    monkeypatch.setenv("INITDATA_MAX_AGE_SEC", "5")
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    user = {"id": 42, "first_name": "Ada", "username": "ada"}
    now = int(datetime.now(timezone.utc).timestamp())
    old_now = now - 10
    pairs = {"query_id": "AAHold", "user": json.dumps(user, separators=(",", ":")), "auth_date": str(old_now)}
    init_data = make_init_data(bot_token, pairs, hash_on="sorted")
    r = client.post("/auth/telegram", headers={"Telegram-Init-Data": init_data})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is False
    assert js["error"]["code"] == "BAD_INPUT"


def test_auth_original_order_signature_variant(client):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    user = {"id": 42, "first_name": "Ada", "username": "ada"}
    now = int(datetime.now(timezone.utc).timestamp())
    pairs_scrambled = {"auth_date": str(now), "user": json.dumps(user, separators=(",", ":")), "query_id": "AAHxyz"}
    init_data_orig = make_init_data(bot_token, pairs_scrambled, hash_on="original")
    r = client.post("/auth/telegram", headers={"Telegram-Init-Data": init_data_orig})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_auth_bogus_signature_param(client):
    now = int(datetime.now(timezone.utc).timestamp())
    bogus = urllib.parse.urlencode({"auth_date": str(now), "signature": "Zm9vYmFy"})
    r = client.post("/auth/telegram", headers={"Telegram-Init-Data": bogus})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is False
    assert js["error"]["code"] == "BAD_INPUT"


def test_auth_missing_bot_token(monkeypatch):
    import os
    from starlette.testclient import TestClient
    # Ensure app imports after env change
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    import importlib
    import sys
    sys.path.insert(0, os.path.abspath("services/market_data"))
    m = importlib.import_module("app.main")
    importlib.reload(m)
    client = TestClient(m.app)
    r = client.post("/auth/telegram", headers={"Telegram-Init-Data": "auth_date=0&hash=deadbeef"})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is False and js["error"]["code"] == "INTERNAL"
