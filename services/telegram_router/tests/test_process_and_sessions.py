import os


def test_test_endpoint_sends_and_fx_format(client, monkeypatch, capture_telegram):
    # Make sure dispatcher returns a fixed FX rate
    import app.app as appmod  # type: ignore

    async def _fake_dispatch(spec, args):
        if spec.get("service") == "fx":
            return {"ok": True, "data": {"rate": 1.1111}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch(spec, args))

    r = client.post("/telegram/test", json={"chat_id": 1001, "text": "/fx eur usd"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(capture_telegram) == 1
    assert capture_telegram[0]["chat_id"] == 1001
    txt = capture_telegram[0]["text"].lower()
    assert "eur/usd" in txt and ("1.1111" in txt or "1,1111" in txt)


def test_owner_gate_denied(monkeypatch):
    # Call process_text directly with a non-owner sender
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx
    
    # Ensure no owner contains 999
    assert 999 not in s.owner_ids

    # Run
    out = appmod.asyncio.run(appmod.process_text(chat_id=1002, sender_id=999, text="/help", ctx=ctx))
    assert out and "not authorized" in out[0].lower()


def test_unknown_command(client, capture_telegram, monkeypatch):
    # Use /telegram/test to go through API path
    r = client.post("/telegram/test", json={"chat_id": 1003, "text": "/doesnotexist"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # No telegram send expected because process_text returns immediate text, but /telegram/test sends it too
    assert len(capture_telegram) == 1
    assert "unknown command" in capture_telegram[0]["text"].lower()


def test_session_flow_buy_prompt_and_merge(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    # Make dispatcher succeed for buy
    async def _fake_dispatch(spec, args):
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch(spec, args))

    # 1) User starts with incomplete command -> prompt usage, session created
    out1 = appmod.asyncio.run(appmod.process_text(chat_id=2001, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/buy", ctx=ctx))
    assert out1 and "use:" in out1[0].lower()
    assert sessions.get(2001) is not None and sessions.get(2001).get("cmd") == "/buy"

    # 2) Next message without command merges into the session -> success and session cleared
    out2 = appmod.asyncio.run(appmod.process_text(chat_id=2001, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="1 aapl 10", ctx=ctx))
    assert out2 and "buy" in out2[0].lower()
    assert sessions.get(2001) is None


def test_price_table_output(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    # Mock quotes from market data
    async def _fake_dispatch(spec, args):
        if spec.get("service") == "market_data":
            return {
                "ok": True,
                "data": {
                    "quotes": [
                        {"symbol": "AAPL.US", "price_eur": 100.0, "open_eur": 90.0, "market": "US"},
                        {"symbol": "BMW.DE", "price_eur": 95.5, "open_eur": 100.0, "market": "DE"},
                    ]
                },
            }
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch(spec, args))

    out = appmod.asyncio.run(appmod.process_text(chat_id=3001, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price aapl bmw.de", ctx=ctx))
    assert out and out[0]
    txt = out[0]
    # Should render a monospaced table surrounded by ``` and include the symbols
    assert txt.startswith("```") and txt.endswith("```")
    assert "AAPL" in txt and "BMW" in txt
