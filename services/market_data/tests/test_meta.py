def test_meta_success_with_symbol_validation(client, monkeypatch):
    # Mock get_quotes used by /meta to validate symbol existence
    from app import api as api_mod  # type: ignore

    async def fake_get_quotes(conn, syms):
        # Return present quotes list for the normalized symbol
        return {"quotes": [{"symbol": syms[0], "price": "1", "price_eur": "1", "ts": "2020-01-01T00:00:00Z"}]}

    monkeypatch.setattr(api_mod, "get_quotes", fake_get_quotes)

    r = client.get("/meta", params={"symbol": "AAPL"})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    data = js["data"]
    assert data["symbol"] == "AAPL.US"
    assert data["asset_class"] in ("Stock", "ETF", "Crypto")


def test_meta_not_found_when_quotes_missing(client, monkeypatch):
    from app import api as api_mod  # type: ignore

    async def empty_quotes(conn, syms):
        return {"quotes": []}

    monkeypatch.setattr(api_mod, "get_quotes", empty_quotes)

    r = client.get("/meta", params={"symbol": "BADS"})
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is False
    assert js["error"]["code"] == "NOT_FOUND"

