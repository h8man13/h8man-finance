from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime

# Common envelope
class ErrorBody(BaseModel):
    code: Literal["BAD_INPUT","NOT_FOUND","UPSTREAM_ERROR","RATE_LIMIT","TIMEOUT","INTERNAL"]
    message: str
    source: Literal["fx","market_data","portfolio_core","eodhd","db"]
    retriable: bool = False
    details: Optional[Dict[str, Any]] = None

class OkEnvelope(BaseModel):
    ok: Literal[True] = True
    data: Dict[str, Any]
    ts: datetime

class ErrEnvelope(BaseModel):
    ok: Literal[False] = False
    error: ErrorBody
    ts: datetime

# Input helpers
class UserContext(BaseModel):
    user_id: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = ""
    username: Optional[str] = None
    language_code: Optional[str] = None

# Specific outputs
class QuoteItem(BaseModel):
    symbol: str
    market: str
    currency: str
    price: str
    price_eur: str
    open: Optional[str] = None
    open_eur: Optional[str] = None
    ts: datetime

class QuotesResponse(BaseModel):
    quotes: List[QuoteItem]

class MetaResponse(BaseModel):
    symbol: str
    asset_class: Literal["ETF","Stock","Crypto"]
    market: Literal["US","XETRA","CRYPTO"]
    currency: Literal["USD","EUR"]

class BenchSeriesPoint(BaseModel):
    label: str
    pct: str
    end_value_eur: Optional[str] = None  # for value series where applicable

class BenchmarksResponse(BaseModel):
    series: Dict[str, List[BenchSeriesPoint]]  # keyed by input symbol, normalized per spec
