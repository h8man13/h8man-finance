"""Pydantic models for portfolio_core."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


class ErrorCode(str, Enum):
    BAD_INPUT = "BAD_INPUT"
    NOT_FOUND = "NOT_FOUND"
    INSUFFICIENT = "INSUFFICIENT"
    CONFLICT = "CONFLICT"
    INTERNAL = "INTERNAL"


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    source: str = "portfolio_core"
    retriable: bool = False
    details: Optional[Dict[str, Any]] = None


class OkEnvelope(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: lambda d: str(d)})

    ok: bool = True
    data: Dict[str, Any]
    ts: datetime = Field(default_factory=datetime.utcnow)
    partial: Optional[bool] = None


class ErrEnvelope(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: lambda d: str(d)})

    ok: bool = False
    error: ErrorBody
    ts: datetime = Field(default_factory=datetime.utcnow)


class UserContext(BaseModel):
    user_id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = ""
    username: Optional[str] = None
    language_code: Optional[str] = None


class HoldingSnapshot(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: lambda d: str(d)})

    symbol: str
    display_name: Optional[str] = None
    asset_class: str
    market: str
    qty_total: Decimal
    price_eur: Decimal
    value_eur: Decimal
    currency: str
    freshness: Optional[str] = None


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: lambda d: str(d)})

    total_value_eur: Decimal
    cash_eur: Decimal
    holdings: List[HoldingSnapshot]


class CashBalance(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: lambda d: str(d)})

    cash_eur: Decimal


class TransactionRecord(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: lambda d: str(d)})

    tx_id: int
    ts: datetime
    type: str
    symbol: Optional[str] = None
    asset_class: Optional[str] = None
    qty: Optional[Decimal] = None
    price_eur: Optional[Decimal] = None
    amount_eur: Optional[Decimal] = None
    cash_delta_eur: Optional[Decimal] = None
    fees_eur: Optional[Decimal] = None


class AllocationSnapshot(BaseModel):
    stock_pct: int
    etf_pct: int
    crypto_pct: int


class AllocationDiff(BaseModel):
    before: AllocationSnapshot
    after: AllocationSnapshot


class AddPositionRequest(BaseModel):
    op_id: str
    symbol: str
    qty: Decimal
    asset_class: Optional[str] = None

    @field_validator("qty")
    @classmethod
    def check_positive_qty(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("qty must be greater than 0")
        return value


class RemovePositionRequest(BaseModel):
    op_id: str
    symbol: str


class CashMutationRequest(BaseModel):
    op_id: str
    amount_eur: Decimal

    @field_validator("amount_eur")
    @classmethod
    def check_positive_amount(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("amount must be greater than 0")
        return value


class TradeRequest(BaseModel):
    op_id: str
    symbol: str
    qty: Decimal
    price_eur: Optional[Decimal] = None
    fees_eur: Optional[Decimal] = None

    @field_validator("qty")
    @classmethod
    def check_trade_qty(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("qty must be greater than 0")
        return value

    @field_validator("fees_eur")
    @classmethod
    def check_fees(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        if value is not None and value < 0:
            raise ValueError("fees must be greater than or equal to 0")
        return value

class AllocationEditRequest(BaseModel):
    op_id: str
    stock_pct: int
    etf_pct: int
    crypto_pct: int

    @field_validator("stock_pct", "etf_pct", "crypto_pct")
    @classmethod
    def clamp_pct(cls, value: int) -> int:
        if value < 0 or value > 100:
            raise ValueError("percentages must be between 0 and 100")
        return value


class RenameRequest(BaseModel):
    op_id: str
    symbol: str
    display_name: str


class TxQuery(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)
