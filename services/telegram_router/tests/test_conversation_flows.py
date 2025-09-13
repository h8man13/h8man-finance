import os


def test_help_via_test_endpoint(client, capture_telegram, monkeypatch):
    # Ensure owner gate allows sending (is set in conftest)
    r = client.post("/telegram/test", json={"chat_id": 5010, "text": "/help"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(capture_telegram) == 1
    txt = capture_telegram[0]["text"].lower()
    assert "commands" in txt
    assert "/price" in txt or "price" in txt


def test_price_interactive_no_quotes_prompts_again_and_sticky(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    # Start interactive
    out1 = appmod.asyncio.run(appmod.process_text(chat_id=5101, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price", ctx=ctx))
    assert out1 and "what symbols" in out1[0].lower()
    assert sessions.get(5101) and sessions.get(5101).get("cmd") == "/price"

    # Reply with symbols but dispatcher yields empty quotes -> prompt again, still sticky
    async def _fake_dispatch_empty(spec, args):
        if spec.get("service") == "market_data":
            return {"ok": True, "data": {"quotes": []}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch_empty(spec, args))
    out2 = appmod.asyncio.run(appmod.process_text(chat_id=5101, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="nvda", ctx=ctx))
    assert out2 and "what symbols" in out2[0].lower()
    assert sessions.get(5101) and sessions.get(5101).get("cmd") == "/price"


def test_price_error_keeps_sticky(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    # Start interactive
    out1 = appmod.asyncio.run(appmod.process_text(chat_id=5201, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price", ctx=ctx))
    assert out1 and sessions.get(5201)

    # Make market_data fail in dispatch
    async def _fake_dispatch_fail(spec, args):
        if spec.get("service") == "market_data":
            return {"ok": False, "error": {"code": "NOT_FOUND", "message": "symbol not recognized"}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch_fail(spec, args))
    out2 = appmod.asyncio.run(appmod.process_text(chat_id=5201, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="nope.us", ctx=ctx))
    assert out2
    low = out2[0].lower()
    # Accept either generic service error or upstream message
    assert ("service error" in low) or ("symbol not recognized" in low)
    # Session remains sticky
    assert sessions.get(5201) and sessions.get(5201).get("cmd") == "/price"


def test_price_switch_command_clears_session(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    appmod.asyncio.run(appmod.process_text(chat_id=5301, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price", ctx=ctx))
    assert sessions.get(5301)
    # Send a new root command
    out = appmod.asyncio.run(appmod.process_text(chat_id=5301, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/help", ctx=ctx))
    assert out and ("commands" in out[0].lower())
    assert sessions.get(5301) is None


def test_fx_inversion_display(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    async def _fake_dispatch(spec, args):
        if spec.get("service") == "fx":
            # USD_EUR = 2.0 -> EUR/USD should display 0.5
            return {"ok": True, "data": {"pair": "USD_EUR", "rate": 2.0}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch(spec, args))
    out = appmod.asyncio.run(appmod.process_text(chat_id=5401, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/fx eur usd", ctx=ctx))
    assert out and out[0]
    txt = out[0].lower()
    assert "eur/usd" in txt and ("0.5" in txt or "0,5" in txt)


def test_price_market_column_defaults_to_us(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    async def _fake_dispatch(spec, args):
        if spec.get("service") == "market_data":
            return {"ok": True, "data": {"quotes": [
                {"symbol": "AAPL.US", "price_eur": 100.0, "open_eur": 100.0},  # no market -> should show US
            ]}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch(spec, args))
    out = appmod.asyncio.run(appmod.process_text(chat_id=5501, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price aapl", ctx=ctx))
    assert out and out[0].startswith("```")
    assert "MARKET" in out[0] and "US" in out[0]
