from typing import Any


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    js = r.json()
    assert js["ok"] is True
    assert js["data"]["status"] == "healthy"
    assert isinstance(js["ts"], str)


def test_openapi(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    js = r.json()
    # contains major endpoints
    paths = js.get("paths", {})
    assert "/quote" in paths
    assert "/benchmarks" in paths
    assert "/meta" in paths
    assert "/health" in paths


def test_cors_get_echo_origin_header(client):
    origin = "https://example.com"
    r = client.get("/health", headers={"Origin": origin})
    # Starlette lowercases headers in the client accessor
    assert r.headers.get("access-control-allow-origin") == origin


def test_cors_preflight(client):
    origin = "https://example.com"
    r = client.options(
        "/quote",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == origin
    assert "GET" in (r.headers.get("access-control-allow-methods") or "")


def test_cors_credentials_and_headers(client):
    origin = "https://example.com"
    r = client.options(
        "/quote",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Content-Type,Telegram-Init-Data",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == origin
    # Some frameworks omit this header on preflight when true; accept missing or true
    val = r.headers.get("access-control-allow-credentials")
    assert val in (None, "true", "True")
    assert "Telegram-Init-Data" in (r.headers.get("access-control-allow-headers") or "")
