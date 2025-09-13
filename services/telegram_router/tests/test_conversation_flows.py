import os


def test_help_via_test_endpoint(client, capture_telegram, monkeypatch):
    # Ensure owner gate allows sending (is set in conftest)
    r = client.post("/telegram/test", json={"chat_id": 5010, "text": "/help"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(capture_telegram) == 1
    txt = capture_telegram[0]["text"].lower()
    assert "commands" in txt
    assert "/price" in txt or "price" in txt
    # Should include blockquote markers for command usage
    assert ">" in capture_telegram[0]["text"]


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
    assert "eur/usd" in txt and ("0.5" in txt or "0,5" in txt or r"0\.5" in txt)


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


def test_price_one_shot_partial_footnote(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    async def _fake_dispatch(spec, args):
        if spec.get("service") == "market_data":
            return {
                "ok": True,
                "partial": True,
                "error": {"code": "NOT_FOUND", "message": "some failed", "details": {"symbols_failed": ["NOPE.US"]}},
                "data": {"quotes": [
                    {"symbol": "AAPL.US", "price_eur": 100.0, "open_eur": 100.0, "market": "US"},
                ]}
            }
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch(spec, args))

    out = appmod.asyncio.run(appmod.process_text(chat_id=5601, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price aapl nope.us", ctx=ctx))
    assert out and out[0]
    assert "Some symbols were not found".lower() in out[0].lower()


def test_price_alias_p_one_shot_and_prompt(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    async def _fake_dispatch_one(spec, args):
        if spec.get("service") == "market_data":
            return {"ok": True, "data": {"quotes": [
                {"symbol": "AAPL.US", "price_eur": 100.0, "open_eur": 95.0, "market": "US", "freshness": "Live"},
            ]}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch_one(spec, args))
    # One-shot
    out1 = appmod.asyncio.run(appmod.process_text(chat_id=5602, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/p aapl", ctx=ctx))
    assert out1 and out1[0].startswith("```") and "AAPL" in out1[0]
    assert sessions.get(5602) is None

    # Prompt
    out2 = appmod.asyncio.run(appmod.process_text(chat_id=5602, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/p", ctx=ctx))
    assert out2 and "what symbols" in out2[0].lower()
    assert sessions.get(5602) and sessions.get(5602).get("cmd") == "/price"


def test_price_interactive_partial_footnote(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    # Start interactive session
    out0 = appmod.asyncio.run(appmod.process_text(chat_id=5603, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price", ctx=ctx))
    assert out0 and sessions.get(5603)

    async def _fake_dispatch_partial(spec, args):
        if spec.get("service") == "market_data":
            return {
                "ok": True,
                "partial": True,
                "error": {"code": "NOT_FOUND", "message": "some failed", "details": {"symbols_failed": ["BAD.US"]}},
                "data": {"quotes": [
                    {"symbol": "AAPL.US", "price_eur": 100.0, "open_eur": 100.0, "market": "US"},
                ]}
            }
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch_partial(spec, args))
    out = appmod.asyncio.run(appmod.process_text(chat_id=5603, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="aapl bad.us", ctx=ctx))
    assert out and "some symbols were not found" in out[0].lower()
    # session remains sticky
    assert sessions.get(5603) and sessions.get(5603).get("cmd") == "/price"


def test_help_via_process_text_clears_sticky():
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    # Create a sticky price session
    appmod.asyncio.run(appmod.process_text(chat_id=5604, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price", ctx=ctx))
    assert sessions.get(5604)
    # Now issue /help via process_text
    out = appmod.asyncio.run(appmod.process_text(chat_id=5604, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/help", ctx=ctx))
    assert out and "commands" in out[0].lower()
    assert sessions.get(5604) is None


def test_unknown_input_without_session():
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    out = appmod.asyncio.run(appmod.process_text(chat_id=5701, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="nvda", ctx=ctx))
    assert out
    low = out[0].lower()
    assert ("unknown input" in low) or ("try /help" in low)


def test_sticky_expired_treated_as_unknown(monkeypatch, tmp_path):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore
    import os, json, time

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    # Start sticky
    out1 = appmod.asyncio.run(appmod.process_text(chat_id=5702, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price", ctx=ctx))
    assert out1 and sessions.get(5702)

    # Expire session by manipulating ts
    sess_dir = os.environ.get("SESSIONS_DIR")
    path = os.path.join(sess_dir, "5702.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["ts"] = 0  # far in the past
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    # Now bare symbol should be unknown input
    out2 = appmod.asyncio.run(appmod.process_text(chat_id=5702, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="nvda", ctx=ctx))
    assert out2
    low2 = out2[0].lower()
    assert ("unknown input" in low2) or ("try /help" in low2)
    assert sessions.get(5702) is None


def test_cancel_and_exit_clear_session():
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    # /cancel
    appmod.asyncio.run(appmod.process_text(chat_id=5801, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price", ctx=ctx))
    assert sessions.get(5801)
    out_c = appmod.asyncio.run(appmod.process_text(chat_id=5801, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/cancel", ctx=ctx))
    assert out_c and "closed" in out_c[0].lower()
    assert sessions.get(5801) is None

    # /exit
    appmod.asyncio.run(appmod.process_text(chat_id=5801, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price", ctx=ctx))
    assert sessions.get(5801)
    out_e = appmod.asyncio.run(appmod.process_text(chat_id=5801, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/exit", ctx=ctx))
    assert out_e and "closed" in out_e[0].lower()
    assert sessions.get(5801) is None


def test_fx_error_handling(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    async def _fake_dispatch_err(spec, args):
        if spec.get("service") == "fx":
            return {"ok": False, "error": {"code": "UPSTREAM_ERROR", "message": "fx down"}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch_err(spec, args))
    out = appmod.asyncio.run(appmod.process_text(chat_id=5901, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/fx", ctx=ctx))
    assert out
    l = out[0].lower()
    assert ("service error" in l) or ("fx down" in l)
    assert "try:" in l


def test_end_to_end_user_flow(monkeypatch):
    """Simulate the flow reported by the user in one chat."""
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    async def _fake_dispatch(spec, args):
        if spec.get("service") == "market_data":
            syms = args.get("symbols") or []
            # normalize inputs in tests
            syms = [str(x).upper() for x in syms]
            if syms == ["AMZN"] or syms == ["GOOG"]:
                return {"ok": True, "data": {"quotes": [{"symbol": f"{syms[0]}.US", "price_eur": 100.0, "open_eur": 100.0, "market": "US"}]}}
            if "NOPE.US" in syms and any(s in ("AMZN","GOOG") for s in syms):
                return {"ok": True, "partial": True, "error": {"code": "NOT_FOUND", "message": "bad", "details": {"symbols_failed": ["NOPE.US"]}}, "data": {"quotes": [{"symbol": "AMZN.US", "price_eur": 100.0, "open_eur": 100.0, "market": "US"}]}}
            if "NOPE.US" in syms and len(syms) == 1:
                return {"ok": False, "error": {"code": "NOT_FOUND", "message": "symbol not recognized"}}
            return {"ok": True, "data": {"quotes": []}}
        if spec.get("service") == "fx":
            return {"ok": True, "data": {"pair": "USD_EUR", "rate": 1.2}}
        return {"ok": True, "data": {}}

    monkeypatch.setattr(appmod.Dispatcher, "dispatch", lambda self, spec, args: _fake_dispatch(spec, args))

    chat = 6001
    owner = (s.owner_ids[0] if s.owner_ids else 0)

    # /p amzn -> table
    o1 = appmod.asyncio.run(appmod.process_text(chat_id=chat, sender_id=owner, text="/p amzn", ctx=ctx))
    assert o1 and o1[0].startswith("```")

    # /p -> prompt
    o2 = appmod.asyncio.run(appmod.process_text(chat_id=chat, sender_id=owner, text="/p", ctx=ctx))
    assert o2 and "what symbols" in o2[0].lower()

    # amzn -> table
    o3 = appmod.asyncio.run(appmod.process_text(chat_id=chat, sender_id=owner, text="amzn", ctx=ctx))
    assert o3 and o3[0].startswith("```")

    # /help -> reply
    o4 = appmod.asyncio.run(appmod.process_text(chat_id=chat, sender_id=owner, text="/help", ctx=ctx))
    assert o4 and "commands" in o4[0].lower()

    # /p goog -> table
    o5 = appmod.asyncio.run(appmod.process_text(chat_id=chat, sender_id=owner, text="/p goog", ctx=ctx))
    assert o5 and o5[0].startswith("```")

    # /fx -> default USD/EUR
    o6 = appmod.asyncio.run(appmod.process_text(chat_id=chat, sender_id=owner, text="/fx", ctx=ctx))
    assert o6 and ("usd/eur" in o6[0].lower())

    # /p amzn nope.us -> partial footnote or service error
    o7 = appmod.asyncio.run(appmod.process_text(chat_id=chat, sender_id=owner, text="/p amzn nope.us", ctx=ctx))
    assert o7 and ("some symbols were not found" in o7[0].lower() or "service error" in o7[0].lower())

