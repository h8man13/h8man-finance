"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from . import db
from .api import router
from .models import ErrEnvelope, ErrorBody, ErrorCode
from .settings import settings


logger = logging.getLogger(settings.APP_NAME)


app = FastAPI(title=settings.APP_NAME)
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    await db.init_db()


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_: Request, exc: RequestValidationError):
    payload = ErrEnvelope(
        error=ErrorBody(
            code=ErrorCode.BAD_INPUT,
            message="invalid input",
            details={"errors": exc.errors()},
        )
    )
    return JSONResponse(status_code=400, content=jsonable_encoder(payload))


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {"ok": True, "status": "healthy"}


__all__ = ["app"]