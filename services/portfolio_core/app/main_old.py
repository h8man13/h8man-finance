"""
Main FastAPI application.
"""
import os
import json
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from decimal import Decimal

import uvicorn
from fastapi import FastAPI, Request, Header, Depends
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from .settings import settings
from .cors import add_cors
from .db import open_db, upsert_user, init_db
from .models import (
    UserContext,
    OkEnvelope,
    ErrEnvelope,
    ErrorBody,
)
# Telegram auth removed - should use market_data service /auth/telegram endpoint
from .api import router as api_router


app = FastAPI(title=settings.APP_NAME)

# Add CORS middleware
add_cors(app, settings)

# ---------- Error handling ----------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    now_iso = datetime.now(timezone.utc).isoformat()
    return JSONResponse(
        {
            "ok": False,
            "error": {
                "code": "BAD_INPUT",
                "message": "invalid input",
                "source": "portfolio_core",
                "retriable": False,
            },
            "ts": now_iso,
        },
        status_code=400,
    )

# ---------- Dependencies ----------
async def user_dep(
    user_id: Optional[int] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    language_code: Optional[str] = None,
) -> UserContext:
    """Extract user context from request."""
    return UserContext(
        user_id=user_id,
        first_name=first_name,
        last_name=last_name or "",
        username=username,
        language_code=language_code,
    )

# ---------- Health check ----------
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "ok": True,
        "data": {"status": "healthy"},
        "ts": datetime.now(timezone.utc).isoformat(),
    }

# ---------- Auth endpoint ----------
# REMOVED: Telegram auth functionality moved to market_data service
# Use market_data service /auth/telegram endpoint instead

@app.post("/auth/telegram")
async def auth_telegram_redirect():
    """Validate Telegram WebApp initData."""
    now_iso = datetime.now(timezone.utc).isoformat()

    def bad_input(msg: str):
        return {
            "ok": False,
            "error": {
                "code": "BAD_INPUT",
                "message": msg,
                "source": "portfolio_core",
                "retriable": False,
            },
            "ts": now_iso,
        }

    if not settings.TELEGRAM_BOT_TOKEN:
        return {
            "ok": False,
            "error": {
                "code": "INTERNAL",
                "message": "BOT token missing",
                "source": "portfolio_core",
                "retriable": False,
            },
            "ts": now_iso,
        }

    # Get initData from header, auth, or body
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

    # Freshness check
    try:
        if "auth_date" in pairs:
            max_age = settings.INITDATA_MAX_AGE_SEC
            age = datetime.now(timezone.utc).timestamp() - float(pairs["auth_date"])
            if age > max_age:
                return bad_input("invalid initData signature")
    except Exception:
        pass

    # Validate signature
    hash_recv = (pairs.get("hash") or "").strip().lower()
    if not hash_recv:
        return bad_input("invalid initData signature")

    sig_ok = False
    expected_set = set(signature_variants(pairs, init_data, settings.TELEGRAM_BOT_TOKEN))
    if hash_recv in expected_set:
        sig_ok = True

    if not sig_ok:
        return bad_input("invalid initData signature")

    # Optional user upsert
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
                async with await open_db() as conn:
                    await upsert_user(conn, user)
        except Exception:
            pass

    return {
        "ok": True,
        "data": {"user_id": user.get("user_id")},
        "ts": now_iso,
    }

# Mount API routes
app.include_router(api_router)

# Initialize app
@app.on_event("startup")
async def startup_event():
    """Run startup tasks."""
    # Initialize database
    await init_db()

# Run standalone
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )