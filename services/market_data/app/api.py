from fastapi import APIRouter, Depends, Query
from fastapi import HTTPException
from typing import List, Optional
from datetime import datetime, timezone
from .db import open_db, upsert_user
from .models import OkEnvelope, ErrEnvelope, ErrorBody, UserContext
from .services.quotes import get_quotes
from .services.benchmarks import get_benchmarks
from .services.meta import get_meta

router = APIRouter()

async def db_dep():
    conn = await open_db()
    try:
        yield conn
    finally:
        await conn.close()

async def user_dep(user_id: Optional[int] = None,
                   first_name: Optional[str] = None,
                   last_name: Optional[str] = None,
                   username: Optional[str] = None,
                   language_code: Optional[str] = None) -> UserContext:
    return UserContext(
        user_id=user_id, first_name=first_name, last_name=last_name or "",
        username=username, language_code=language_code
    )

def ok(data: dict) -> OkEnvelope:
    return OkEnvelope(ok=True, data=data, ts=datetime.now(timezone.utc))

def err(code: str, message: str, source: str, retriable: bool=False, details=None) -> ErrEnvelope:
    return ErrEnvelope(
        ok=False,
        error=ErrorBody(code=code, message=message, source=source, retriable=retriable, details=details),
        ts=datetime.now(timezone.utc),
    )

@router.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "market_data", "ts": datetime.now(timezone.utc).isoformat()}

@router.get("/quote", response_model=OkEnvelope | ErrEnvelope)
async def quote(symbols: str = Query(..., description="Comma separated symbols"),
                uc: UserContext = Depends(user_dep),
                conn=Depends(db_dep)):
    try:
        await upsert_user(conn, uc.dict())
        syms = [s for s in symbols.split(",") if s.strip()]
        if not syms or len(syms) > 10:
            return err("BAD_INPUT", "symbols must be 1..10", "market_data")
        data = await get_quotes(conn, syms)
        return ok(data)
    except Exception as e:
        return err("UPSTREAM_ERROR", str(e), "eodhd", retriable=True)

@router.get("/benchmarks", response_model=OkEnvelope | ErrEnvelope)
async def benchmarks(period: str = Query(..., regex="^(d|w|m|y)$"),
                     symbols: str = Query(...),
                     uc: UserContext = Depends(user_dep),
                     conn=Depends(db_dep)):
    try:
        await upsert_user(conn, uc.dict())
        syms = [s for s in symbols.split(",") if s.strip()]
        data = await get_benchmarks(conn, period, syms)
        return ok(data)
    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "market_data")
    except Exception as e:
        return err("UPSTREAM_ERROR", str(e), "eodhd", retriable=True)

@router.get("/meta", response_model=OkEnvelope | ErrEnvelope)
async def meta(symbol: str,
               uc: UserContext = Depends(user_dep),
               conn=Depends(db_dep)):
    try:
        await upsert_user(conn, uc.dict())
        data = await get_meta(conn, symbol)
        return ok(data)
    except Exception as e:
        return err("INTERNAL", str(e), "market_data")
