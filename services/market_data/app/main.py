import os
import json
import urllib.parse
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .settings import settings
from .api import router as api_router
from .cors import add_cors
from .middleware import QuoteShapeMiddleware, AuthShieldMiddleware
from .telegram import (
    signature_variants,
    verify_ed25519,
)

# ---------- App ----------
app = FastAPI(title=getattr(settings, "APP_NAME", "market_data"))

def _get(name: str, default=None):
    if hasattr(settings, name):
        return getattr(settings, name)
    return os.getenv(name, default)

def _to_list(val):
    if not val:
        return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    return [str(x).strip() for x in arr if str(x).strip()]
            except Exception:
                pass
        return [x.strip() for x in s.split(",") if x.strip()]
    return [str(val).strip()]

# ---------- CORS ----------
add_cors(app, settings)

app.add_middleware(QuoteShapeMiddleware)

# ---------- Health ----------
@app.get("/health")
async def health():
    # Matches your test expectation exactly
    return {"ok": True, "data": {"status": "healthy"}, "ts": datetime.now(timezone.utc).isoformat()}

# ---------- /benchmarks period guard (pre-Pydantic) ----------
@app.middleware("http")
async def _benchmarks_period_guard(request: Request, call_next):
    if request.method == "GET" and request.url.path.endswith("/benchmarks"):
        try:
            qp = request.query_params
            if "period" not in qp or not (qp.get("period") or "").strip():
                now_iso = datetime.now(timezone.utc).isoformat()
                return JSONResponse(
                    {
                        "ok": False,
                        "error": {
                            "code": "BAD_INPUT",
                            "message": "period required: d|w|m|y",
                            "source": "market_data",
                            "retriable": False,
                        },
                        "ts": now_iso,
                    },
                    status_code=400,
                )
        except Exception:
            pass
    return await call_next(request)

# ---------- Validation fallback (other 422s) ----------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    now_iso = datetime.now(timezone.utc).isoformat()
    return JSONResponse(
        {
            "ok": False,
            "error": {
                "code": "BAD_INPUT",
                "message": "invalid input",
                "source": "market_data",
                "retriable": False,
            },
            "ts": now_iso,
        },
        status_code=400,
    )

# ---------- Telegram helpers moved to app/telegram.py ----------

app.add_middleware(AuthShieldMiddleware)

# ---------- /auth/telegram ----------
@app.post("/auth/telegram")
async def auth_telegram(
    request: Request,
    authorization: str | None = Header(default=None),
    telegram_init_data: str | None = Header(default=None, alias="Telegram-Init-Data"),
):
    now_iso = datetime.now(timezone.utc).isoformat()

    def bad_input(msg: str):
        return {
            "ok": False,
            "error": {
                "code": "BAD_INPUT",
                "message": msg,
                "source": "market_data",
                "retriable": False,
            },
            "ts": now_iso,
        }

    bot_token = _get("TELEGRAM_BOT_TOKEN", "") or ""
    if not bot_token:
        return {
            "ok": False,
            "error": {
                "code": "INTERNAL",
                "message": "BOT token missing",
                "source": "market_data",
                "retriable": False,
            },
            "ts": now_iso,
        }

    # Priority: header, Authorization tma, body (json or text)
    try:
        init_data = None
        if telegram_init_data and telegram_init_data.strip():
            init_data = telegram_init_data.strip()
        elif authorization and authorization.lower().startswith("tma "):
            init_data = authorization[4:].strip()
        else:
            raw = await request.body()
            ctype = (request.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                try:
                    j = json.loads(raw.decode("utf-8", "ignore"))
                    if isinstance(j, dict):
                        init_data = j.get("initData")
                except Exception:
                    pass
            if not init_data:
                init_data = raw.decode("utf-8", "ignore").strip() or None
    except Exception:
        return bad_input("invalid initData signature")

    if not isinstance(init_data, str) or not init_data:
        return bad_input("invalid initData signature")

    # Parse decoded pairs
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return bad_input("invalid initData signature")

    # Freshness guard if auth_date present
    try:
        if "auth_date" in pairs:
            max_age = int(_get("INITDATA_MAX_AGE_SEC", "3600") or "3600")
            age = datetime.now(timezone.utc).timestamp() - float(pairs["auth_date"])
            if age > max_age:
                return bad_input("invalid initData signature")
    except Exception:
        pass

    # HMAC validation
    hash_recv = (pairs.get("hash") or "").strip().lower()
    sig_ok = False
    if hash_recv:
        expected_set = set(signature_variants(pairs, init_data, bot_token))
        if hash_recv in expected_set:
            sig_ok = True

    # Ed25519 fallback
    if not sig_ok and "signature" in pairs:
        sig_ok = verify_ed25519(pairs, bot_token)

    if not sig_ok:
        return bad_input("invalid initData signature")

    # Optional user upsert, non-fatal
    user = {}
    if "user" in pairs:
        try:
            u = json.loads(pairs["user"])
            if isinstance(u, dict):
                user = {
                    "user_id": u.get("id"),
                    "first_name": u.get("first_name"),
                    "last_name": (u.get("last_name") or ""),
                    "username": u.get("username"),
                    "language_code": u.get("language_code"),
                }
                try:
                    from .db import open_db, upsert_user  # type: ignore
                    conn = await open_db()
                    try:
                        await upsert_user(conn, user)
                    finally:
                        await conn.close()
                except Exception:
                    pass
        except Exception:
            pass

    return {"ok": True, "data": {"user_id": user.get("user_id")}, "ts": now_iso}

# ---------- Mount remaining API ----------
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=getattr(settings, "HOST", "0.0.0.0"),
        port=getattr(settings, "PORT", 8000),
        reload=False,
    )
