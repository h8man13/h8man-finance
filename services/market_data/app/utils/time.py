from datetime import datetime
from zoneinfo import ZoneInfo
from .settings import settings

TZ = ZoneInfo(settings.TZ)

def now_utc_iso() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat()

def to_berlin(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ)
