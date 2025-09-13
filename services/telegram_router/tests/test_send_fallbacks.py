import types


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []  # collect payloads

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        self.requests.append(json)
        if self._responses:
            data = self._responses.pop(0)
        else:
            data = {"ok": True}
        return FakeResponse(data)


def _install_fake_httpx(monkeypatch, appmod, responses):
    holder = {}

    def _factory(*args, **kwargs):
        c = FakeAsyncClient(responses)
        holder["client"] = c
        return c

    monkeypatch.setattr(appmod.httpx, "AsyncClient", _factory)
    return holder


def test_send_markdown_strict_retry_success(monkeypatch):
    import app.app as appmod  # type: ignore
    from app.core.templates import safe_escape_mdv2_with_fences  # type: ignore

    # First attempt fails, second (strict) succeeds
    holder = _install_fake_httpx(monkeypatch, appmod, responses=[{"ok": False, "error_code": 400}, {"ok": True}])

    text = "Hello (world) *bold*"
    appmod.asyncio.run(appmod.send_telegram_message("token", 123, text, parse_mode="MarkdownV2"))

    client = holder["client"]
    assert len(client.requests) == 2
    # Both attempts use MarkdownV2
    assert client.requests[0].get("parse_mode") == "MarkdownV2"
    assert client.requests[1].get("parse_mode") == "MarkdownV2"
    # Second text is strictly escaped outside fences
    assert client.requests[1]["text"] == safe_escape_mdv2_with_fences(text, strict=True)


def test_send_html_fallback_success(monkeypatch):
    import app.app as appmod  # type: ignore

    # First and second attempts fail, HTML succeeds
    holder = _install_fake_httpx(monkeypatch, appmod, responses=[{"ok": False}, {"ok": False}, {"ok": True}])

    text = "*Bold* and `code`\n```\nTABLE\n```"
    appmod.asyncio.run(appmod.send_telegram_message("token", 123, text, parse_mode="MarkdownV2"))

    client = holder["client"]
    assert len(client.requests) == 3
    # Third attempt is HTML
    assert client.requests[2].get("parse_mode") == "HTML"
    assert "<b>Bold</b>" in client.requests[2]["text"] or "<code>code</code>" in client.requests[2]["text"]


def test_send_plain_text_last_resort(monkeypatch):
    import app.app as appmod  # type: ignore

    # All three attempts fail, plain text succeeds
    holder = _install_fake_httpx(monkeypatch, appmod, responses=[{"ok": False}, {"ok": False}, {"ok": False}, {"ok": True}])

    text = "Text with tricky _underscores_ and (parens)"
    appmod.asyncio.run(appmod.send_telegram_message("token", 123, text, parse_mode="MarkdownV2"))

    client = holder["client"]
    assert len(client.requests) == 4
    # Last attempt has no parse_mode (plain text)
    assert "parse_mode" not in client.requests[3]
    assert client.requests[3]["text"] == text

