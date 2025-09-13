def test_price_prompt_uses_blocks(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.app import deps  # type: ignore

    ctx = deps()
    s, registry, copies, ranking, sessions, idemp, dispatcher, http = ctx

    out = appmod.asyncio.run(appmod.process_text(chat_id=8101, sender_id=(s.owner_ids[0] if s.owner_ids else 0), text="/price", ctx=ctx))
    assert out and out[0]
    low = out[0].lower()
    assert "what symbols" in low
    assert "example:" in low
