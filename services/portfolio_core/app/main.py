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
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown (if needed)

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

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
    """Redirect to market_data service for Telegram auth."""
    return {
        "ok": False,
        "error": {
            "code": "BAD_INPUT",
            "message": "Telegram auth moved to market_data service. Use market_data /auth/telegram endpoint instead.",
            "source": "portfolio_core",
            "retriable": False,
        },
        "ts": datetime.now(timezone.utc).isoformat(),
    }

# Mount API routes
app.include_router(api_router)

# Startup event moved to lifespan context manager above

# Run standalone
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )