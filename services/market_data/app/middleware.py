import json
from datetime import datetime, timezone
from fastapi.responses import JSONResponse
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware


def _to_float(x):
    try:
        return float(x) if x not in (None, "") else None
    except Exception:
        return None


def _normalize_quote_item(item: dict) -> dict:
    sym = item.get("symbol")
    ccy = item.get("ccy") or item.get("currency")
    price_ccy = _to_float(item.get("price") or item.get("price_ccy"))
    open_ccy = _to_float(item.get("open") or item.get("open_ccy"))
    price_eur = _to_float(item.get("price_eur"))
    open_eur = _to_float(item.get("open_eur"))
    ts_price = item.get("ts") or item.get("ts_price")
    pct = None
    if price_ccy is not None and open_ccy not in (None, 0):
        pct = round(((price_ccy / open_ccy) - 1.0) * 100.0, 2)
    base = {
        "symbol": sym,
        "ccy": ccy,
        "price_ccy": price_ccy,
        "price_eur": price_eur,
        "open_ccy": open_ccy,
        "open_eur": open_eur,
        "pct_since_open": pct,
        "ts_price": ts_price,
    }
    # Pass through provider and freshness if present to aid UIs like Telegram router
    if "provider" in item:
        base["provider"] = item.get("provider")
    if "freshness" in item:
        base["freshness"] = item.get("freshness")
    if "freshness_note" in item:
        base["freshness_note"] = item.get("freshness_note")
    if "fresh_time" in item:
        base["fresh_time"] = item.get("fresh_time")
    return base


def _safe_headers(headers) -> dict:
    out = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in ("content-length", "transfer-encoding"):
            continue
        out[k] = v
    return out


class QuoteShapeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method != "GET" or not request.url.path.endswith("/quote"):
            return await call_next(request)

        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body = b""
        try:
            async for chunk in response.body_iterator:
                body += chunk
        except Exception:
            return response

        headers = _safe_headers(response.headers)
        try:
            payload = json.loads(body or b"{}")
        except Exception:
            return Response(content=body, status_code=response.status_code, headers=headers, media_type=content_type)

        try:
            if isinstance(payload, dict) and payload.get("ok") and payload.get("data", {}).get("quotes"):
                quotes = payload["data"]["quotes"]
                if isinstance(quotes, list):
                    payload["data"]["quotes"] = [_normalize_quote_item(q) for q in quotes if isinstance(q, dict)]
                    return JSONResponse(content=payload, status_code=response.status_code, headers=headers)
        except Exception:
            return Response(content=body, status_code=response.status_code, headers=headers, media_type=content_type)

        return Response(content=body, status_code=response.status_code, headers=headers, media_type=content_type)


class AuthShieldMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path != "/auth/telegram":
            return await call_next(request)
        try:
            return await call_next(request)
        except Exception:
            now_iso = datetime.now(timezone.utc).isoformat()
            return JSONResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "BAD_INPUT",
                        "message": "invalid initData signature",
                        "source": "market_data",
                        "retriable": False,
                    },
                    "ts": now_iso,
                },
                status_code=200,
            )
