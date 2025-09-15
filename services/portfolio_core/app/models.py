"""
Models for data validation and serialization.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class Portfolio(BaseModel):
    id: Optional[int] = None
    user_id: int
    name: str
    description: str
    base_currency: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Position(BaseModel):
    id: Optional[int] = None
    portfolio_id: int
    symbol: str
    quantity: Decimal
    avg_price: Decimal
    currency: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Transaction(BaseModel):
    id: Optional[int] = None
    position_id: int
    quantity: Decimal
    price: Decimal
    date: datetime
    created_at: Optional[datetime] = None


class PortfolioSnapshot(BaseModel):
    id: Optional[int] = None
    portfolio_id: int
    date: datetime
    total_value: Decimal
    cash_value: Decimal
    invested_value: Decimal
    created_at: Optional[datetime] = None


class PositionPerformance(BaseModel):
    position_id: int
    symbol: str
    cost_basis: Decimal
    market_value: Decimal
    unrealized_gain: Decimal
    total_return_pct: Decimal
    calculated_at: datetime


class ErrorBody(BaseModel):
    code: str
    message: str
    source: str
    retriable: bool = False
    details: Optional[Dict[str, Any]] = None


class OkEnvelope(BaseModel):
    ok: bool = True
    data: Dict[str, Any]
    ts: datetime
    partial: Optional[bool] = None
    error: Optional[ErrorBody] = None


class ErrEnvelope(BaseModel):
    ok: bool = False
    error: ErrorBody
    ts: datetime


class UserContext(BaseModel):
    user_id: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = Field(default="")
    username: Optional[str] = None
    language_code: Optional[str] = None


class Position(BaseModel):
    user_id: int
    symbol: str
    market: str
    asset_class: str
    qty: Decimal
    avg_cost_ccy: Decimal
    avg_cost_eur: Decimal
    ccy: str
    nickname: Optional[str] = None
    updated_at: datetime


class CashBalance(BaseModel):
    user_id: int
    amount_eur: Decimal
    updated_at: datetime


class Transaction(BaseModel):
    tx_id: Optional[int] = None
    user_id: int
    ts: datetime
    type: str
    symbol: Optional[str] = None
    qty: Optional[Decimal] = None
    price_ccy: Optional[Decimal] = None
    ccy: Optional[str] = None
    amount_eur: Decimal
    fx_rate_used: Optional[Decimal] = None
    note: Optional[str] = None


class Snapshot(BaseModel):
    user_id: int
    date: datetime
    value_eur: Decimal
    net_external_flows_eur: Decimal
    daily_r_t: Optional[Decimal] = None


class TargetAllocation(BaseModel):
    user_id: int
    etf_target_pct: int
    stock_target_pct: int
    crypto_target_pct: int
    updated_at: datetime