import os
import json


def _make_update(update_id: int, chat_id: int, sender_id: int, text: str):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "from": {"id": sender_id, "is_bot": False, "username": "tester"},
            "chat": {"id": chat_id},
            "text": text,
        },
    }


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    assert isinstance(js["ts"], int)


def test_webhook_mode_and_auth(client, monkeypatch):
    # Ensure webhook mode
    monkeypatch.setenv("TELEGRAM_MODE", "webhook")
    # Missing header -> 401
    r = client.post("/telegram/webhook", content=b"{}", headers={"content-type": "application/json"})
    assert r.status_code == 401
    # Wrong secret -> 401
    r = client.post(
        "/telegram/webhook",
        content=b"{}",
        headers={"content-type": "application/json", "X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert r.status_code == 401
    # Correct secret, empty payload -> 200 ok
    r = client.post(
        "/telegram/webhook",
        content=b"{}",
        headers={
            "content-type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": os.environ.get("TELEGRAM_WEBHOOK_SECRET", "whsec_test"),
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_webhook_process_text_and_idempotency(client, monkeypatch, capture_telegram):
    # Force webhook mode and set secret
    monkeypatch.setenv("TELEGRAM_MODE", "webhook")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "whsec_test")

    # Patch Dispatcher.dispatch to avoid external calls and return OK
    import app.app as appmod  # type: ignore

    async def _fake_dispatch(spec, args):
        if spec.get("service") == "fx":
            return {"ok": True, "data": {"rate": 1.2345}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch(spec, args))

    # Valid update -> message sent once
    upd = _make_update(update_id=100, chat_id=999, sender_id=42, text="/fx eur usd")
    r = client.post(
        "/telegram/webhook",
        json=upd,
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    # Give background task a brief moment
    import time as _t
    _t.sleep(0.05)

    # Duplicate update_id -> ignored by idempotency (no additional send)
    r2 = client.post(
        "/telegram/webhook",
        json=upd,
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
    )
    assert r2.status_code == 200 and r2.json()["ok"] is True
    _t.sleep(0.05)

    # We cannot guarantee background scheduling timing, but at least one send should have happened
    # and never more than one for the same update ID.
    assert len(capture_telegram) in (1,)
    assert capture_telegram[0]["chat_id"] == 999
    assert "EUR/USD" in capture_telegram[0]["text"] or "eur/usd" in capture_telegram[0]["text"].lower()
