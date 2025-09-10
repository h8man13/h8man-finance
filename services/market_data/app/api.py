from fastapi import APIRouter, Depends, Query
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from decimal import InvalidOperation

from .db import open_db, upsert_user
from .models import OkEnvelope, ErrEnvelope, ErrorBody, UserContext
from .services.quotes import get_quotes
from .services.benchmarks import get_benchmarks
from .utils.symbols import normalize_symbol
from .services.meta import get_meta

router = APIRouter()


async def db_dep():
    conn = await open_db()
    try:
        yield conn
    finally:
        await conn.close()


async def user_dep(
    user_id: Optional[int] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    language_code: Optional[str] = None,
) -> UserContext:
    return UserContext(
        user_id=user_id,
        first_name=first_name,
        last_name=last_name or "",
        username=username,
        language_code=language_code,
    )


def ok(data: dict, partial: Optional[bool] = None, error: Optional[ErrorBody] = None) -> OkEnvelope:
    return OkEnvelope(ok=True, data=data, ts=datetime.now(timezone.utc), partial=partial, error=error)


def err(code: str, message: str, source: str, retriable: bool = False, details=None) -> ErrEnvelope:
    return ErrEnvelope(
        ok=False,
        error=ErrorBody(code=code, message=message, source=source, retriable=retriable, details=details),
        ts=datetime.now(timezone.utc),
    )


def _to_float(x) -> Optional[float]:
    try:
        return float(x) if x is not None and x != "" else None
    except Exception:
        return None


def _normalize_benchmarks(period: str, raw: Dict[str, Any], symbols: List[str]) -> Dict[str, Any]:
    """
    Emit spec shape:

    period='d':
      data.benchmarks = { SYMBOL: { n_pct: float, o_pct: float } }

    period='w':
      data.benchmarks = { SYMBOL: [ { label: Mon..Sun, pct: float }, ... 7 items ] }
      - Enforce Mon..Sun order
      - Deduplicate labels (keep last occurrence)
      - Fill missing weekend days with 0.0

    period='m':
      data.benchmarks = { SYMBOL: [ { label: W0, pct }, { label: W-1, pct }, { label: W-2, pct }, { label: W-3, pct } ] }
      - Enforce W0..W-3 order
      - Keep only labels provided by services (no invented values)

    period='y':
      Pass through array but coerce pct to float; if services return months out of order you may sort Jan..Dec here later.
    """
    def _to_float(x):
        try:
            return float(x) if x is not None and x != "" else None
        except Exception:
            return None

    # pick source dict
    src = {}
    if isinstance(raw, dict):
        if isinstance(raw.get("benchmarks"), dict):
            src = raw["benchmarks"]
        elif isinstance(raw.get("series"), dict):
            src = raw["series"]

    out: Dict[str, Any] = {}
    day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    week_order = ["W0", "W-1", "W-2", "W-3"]

    for s in symbols:
        v = src.get(s)

        if period == "d":
            # Already in dict form?
            if isinstance(v, dict) and ("n_pct" in v or "o_pct" in v):
                out[s] = {
                    "n_pct": _to_float(v.get("n_pct")),
                    "o_pct": _to_float(v.get("o_pct")),
                }
            # List with {"label":"today","pct":...}
            elif isinstance(v, list) and v:
                today_item = next((it for it in v if str(it.get("label", "")).lower() == "today"), v[0])
                n = _to_float(today_item.get("pct"))
                out[s] = {"n_pct": n if n is not None else 0.0, "o_pct": 0.0}
            else:
                out[s] = {"n_pct": None, "o_pct": 0.0}

        elif period == "w":
            # Build last-value map per weekday, then emit Mon..Sun filling missing days with 0.0
            daymap: Dict[str, Optional[float]] = {}
            if isinstance(v, list):
                for it in v:
                    lbl = str(it.get("label", "")).strip()
                    if lbl in day_order:
                        daymap[lbl] = _to_float(it.get("pct"))
            arr = []
            for d in day_order:
                val = daymap.get(d)
                arr.append({"label": d, "pct": val if val is not None else 0.0})
            out[s] = arr

        elif period == "m":
            # Reorder to W0..W-3, keep only provided labels
            wmap: Dict[str, Optional[float]] = {}
            if isinstance(v, list):
                for it in v:
                    lbl = str(it.get("label", "")).strip()
                    if lbl in week_order:
                        wmap[lbl] = _to_float(it.get("pct"))
            arr = [{"label": lbl, "pct": wmap[lbl]} for lbl in week_order if lbl in wmap]
            out[s] = arr

        else:  # period == 'y'
            arr: List[Dict[str, Any]] = []
            if isinstance(v, list):
                for it in v:
                    arr.append({"label": it.get("label"), "pct": _to_float(it.get("pct"))})
            out[s] = arr

    return {"benchmarks": out}


# Health endpoint is provided in app/main.py to match expected shape


@router.get("/quote", response_model=OkEnvelope | ErrEnvelope)
async def quote(
    symbols: str = Query(..., description="Comma separated symbols"),
    uc: UserContext = Depends(user_dep),
    conn=Depends(db_dep),
):
    try:
        await upsert_user(conn, uc.model_dump())

        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        if not syms or len(syms) > 10:
            return err("BAD_INPUT", "max 10 symbols", "market_data")

        # Fast path: batch call
        try:
            data = await get_quotes(conn, syms)
            return ok(data)
        except Exception as e_batch:
            # Slow path: isolate per symbol so one failure cannot kill the batch
            quotes: List[dict] = []
            failed: List[str] = []
            for s in syms:
                try:
                    d = await get_quotes(conn, [s])
                    q = (d or {}).get("quotes") or []
                    if q:
                        quotes.extend(q)
                    else:
                        failed.append(s)
                except Exception:
                    failed.append(s)

            if quotes:
                eb = (
                    ErrorBody(
                        code="NOT_FOUND",
                        message=f"{len(failed)} or more symbol(s) failed",
                        source="eodhd",
                        retriable=False,
                        details={"symbols_failed": failed} if failed else None,
                    )
                    if failed
                    else None
                )
                return ok({"quotes": quotes}, partial=bool(failed), error=eb)

            return err("UPSTREAM_ERROR", str(e_batch), "eodhd", retriable=True)

    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "market_data")
    except Exception as e:
        return err("UPSTREAM_ERROR", str(e), "eodhd", retriable=True)


@router.get("/benchmarks", response_model=OkEnvelope | ErrEnvelope)
async def benchmarks(
    period: str = Query(..., pattern="^(d|w|m|y)$"),
    symbols: str = Query(...),
    uc: UserContext = Depends(user_dep),
    conn=Depends(db_dep),
):
    try:
        await upsert_user(conn, uc.model_dump())
        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        syms_n = [normalize_symbol(s) for s in syms]

        raw = await get_benchmarks(conn, period, syms_n)
        data = _normalize_benchmarks(period, raw, syms_n)
        return ok(data)

    except ValueError as ve:
        return err("BAD_INPUT", str(ve), "market_data")
    except Exception as e:
        return err("UPSTREAM_ERROR", str(e), "eodhd", retriable=True)


@router.get("/meta", response_model=OkEnvelope | ErrEnvelope)
async def meta(
    symbol: str,
    uc: UserContext = Depends(user_dep),
    conn=Depends(db_dep),
):
    try:
        await upsert_user(conn, uc.model_dump())

        # 1) Build classification as before (syntax-based)
        data = await get_meta(conn, symbol)

        # 2) Validate symbol existence via quotes for a single symbol
        norm_sym = data.get("symbol") if isinstance(data, dict) else None
        norm_sym = norm_sym or symbol

        try:
            q = await get_quotes(conn, [norm_sym])
            if not q or not q.get("quotes"):
                return ErrEnvelope(
                    ok=False,
                    error=ErrorBody(
                        code="NOT_FOUND",
                        message="symbol not recognized",
                        source="market_data",
                        retriable=False,
                        details={"symbol": norm_sym},
                    ),
                    ts=datetime.now(timezone.utc),
                )
        except (InvalidOperation, ValueError, TypeError) as ve:
            return ErrEnvelope(
                ok=False,
                error=ErrorBody(
                    code="NOT_FOUND",
                    message="symbol not recognized",
                    source="market_data",
                    retriable=False,
                    details={"symbol": norm_sym, "reason": str(ve)},
                ),
                ts=datetime.now(timezone.utc),
            )
        except Exception as e:
            return ErrEnvelope(
                ok=False,
                error=ErrorBody(
                    code="UPSTREAM_ERROR",
                    message=str(e),
                    source="eodhd",
                    retriable=True,
                ),
                ts=datetime.now(timezone.utc),
            )

        return OkEnvelope(ok=True, data=data, ts=datetime.now(timezone.utc))

    except ValueError as ve:
        return ErrEnvelope(
            ok=False,
            error=ErrorBody(code="BAD_INPUT", message=str(ve), source="market_data", retriable=False),
            ts=datetime.now(timezone.utc),
        )
    except Exception as e:
        return ErrEnvelope(
            ok=False,
            error=ErrorBody(code="INTERNAL", message=str(e), source="market_data", retriable=False),
            ts=datetime.now(timezone.utc),
        )
