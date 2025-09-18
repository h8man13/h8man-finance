"""FastAPI router exposing portfolio_core endpoints."""
from __future__ import annotations

from decimal import Decimal
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from . import db
from .models import (
    AddPositionRequest,
    AllocationEditRequest,
    CashMutationRequest,
    ErrEnvelope,
    ErrorBody,
    ErrorCode,
    OkEnvelope,
    RemovePositionRequest,
    RenameRequest,
    TradeRequest,
    TxQuery,
    UserContext,
)
from .services import BusinessError, PortfolioService


router = APIRouter()


async def db_dep():
    conn = await db.open_db()
    try:
        yield conn
    finally:
        await conn.close()


async def user_dep(
    user_id: int = Query(...),
    first_name: str | None = Query(None),
    last_name: str | None = Query(None),
    username: str | None = Query(None),
    language_code: str | None = Query(None),
) -> UserContext:
    return UserContext(
        user_id=user_id,
        first_name=first_name,
        last_name=last_name,
        username=username,
        language_code=language_code,
    )


def success(data: dict) -> JSONResponse:
    payload = OkEnvelope(data=data)
    return JSONResponse(content=jsonable_encoder(payload))


def failure(code: ErrorCode, message: str, *, retriable: bool = False, details: dict | None = None, status_code: int = 400) -> JSONResponse:
    error = ErrEnvelope(error=ErrorBody(code=code, message=message, retriable=retriable, details=details))
    return JSONResponse(content=jsonable_encoder(error), status_code=status_code)


@router.get("/portfolio")
async def get_portfolio(uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    snapshot = await service.portfolio(uc)
    return success(snapshot.model_dump())


@router.post("/add")
async def add_position(payload: AddPositionRequest, uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    try:
        result = await service.add(uc, payload)
        return success(result)
    except BusinessError as exc:
        return failure(exc.code, exc.message, details=exc.details)


@router.post("/remove")
async def remove_position(payload: RemovePositionRequest, uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    try:
        result = await service.remove(uc, payload)
        return success(result)
    except BusinessError as exc:
        status = 404 if exc.code == ErrorCode.NOT_FOUND else 400
        return failure(exc.code, exc.message, details=exc.details, status_code=status)


@router.get("/cash")
async def get_cash_balance(uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    balance = await service.cash_balance(uc)
    return success({"cash_eur": balance.cash_eur})


@router.post("/cash_add")
async def cash_add(payload: CashMutationRequest, uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    try:
        result = await service.cash_add(uc, payload)
        return success(result)
    except BusinessError as exc:
        return failure(exc.code, exc.message, details=exc.details)


@router.post("/cash_remove")
async def cash_remove(payload: CashMutationRequest, uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    try:
        result = await service.cash_remove(uc, payload)
        return success(result)
    except BusinessError as exc:
        status = 400 if exc.code != ErrorCode.NOT_FOUND else 404
        return failure(exc.code, exc.message, details=exc.details, status_code=status)


@router.post("/buy")
async def buy(payload: TradeRequest, uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    try:
        result = await service.buy(uc, payload)
        return success(result)
    except BusinessError as exc:
        status = 400 if exc.code != ErrorCode.NOT_FOUND else 404
        return failure(exc.code, exc.message, details=exc.details, status_code=status)


@router.post("/sell")
async def sell(payload: TradeRequest, uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    try:
        result = await service.sell(uc, payload)
        return success(result)
    except BusinessError as exc:
        status = 400 if exc.code != ErrorCode.NOT_FOUND else 404
        return failure(exc.code, exc.message, details=exc.details, status_code=status)


@router.get("/tx")
async def list_transactions(
    limit: int = Query(10, ge=1, le=50),
    uc: UserContext = Depends(user_dep),
    conn=Depends(db_dep),
):
    service = PortfolioService(conn)
    records = await service.transactions(uc, TxQuery(limit=limit))
    data = {"transactions": [r.model_dump() for r in records], "count": len(records)}
    return success(data)


@router.get("/allocation")
async def get_allocation(uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    data = await service.allocation(uc)
    return success({k: v.model_dump() for k, v in data.items()})


@router.post("/allocation_edit")
async def allocation_edit(payload: AllocationEditRequest, uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    try:
        result = await service.allocation_edit(uc, payload)
        return success(result)
    except BusinessError as exc:
        return failure(exc.code, exc.message, details=exc.details)


@router.post("/rename")
async def rename(payload: RenameRequest, uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    try:
        result = await service.rename(uc, payload)
        return success(result)
    except BusinessError as exc:
        status = 404 if exc.code == ErrorCode.NOT_FOUND else 400
        return failure(exc.code, exc.message, details=exc.details, status_code=status)




@router.get("/portfolio_snapshot")
async def api_portfolio_snapshot(period: str = Query("d"), uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    data = await service.portfolio_snapshot(uc, period)
    return success({"snapshot": data})


@router.get("/portfolio_summary")
async def api_portfolio_summary(period: str = Query("m"), uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    data = await service.portfolio_summary(uc, period)
    return success({"summary": data})


@router.get("/portfolio_breakdown")
async def api_portfolio_breakdown(period: str = Query("y"), uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    data = await service.portfolio_breakdown(uc, period)
    return success({"breakdown": data})


@router.get("/portfolio_digest")
async def api_portfolio_digest(period: str = Query("m"), uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    data = await service.portfolio_digest(uc, period)
    return success({"digest": data})


@router.get("/portfolio_movers")
async def api_portfolio_movers(period: str = Query("d"), uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    data = await service.portfolio_movers(uc, period)
    return success({"movers": data})


@router.get("/po_if")
async def api_po_if(scope: str = Query(""), delta_pct: float = Query(...), uc: UserContext = Depends(user_dep), conn=Depends(db_dep)):
    service = PortfolioService(conn)
    try:
        data = await service.what_if(uc, scope or "*", Decimal(str(delta_pct)))
        return success({"what_if": data})
    except BusinessError as exc:
        status = 404 if exc.code == ErrorCode.NOT_FOUND else 400
        return failure(exc.code, exc.message, details=exc.details, status_code=status)





