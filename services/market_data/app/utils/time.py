from datetime import datetime, time, timezone
from typing import Dict, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from ..settings import settings

TZ = ZoneInfo(settings.TZ)

def now_utc_iso() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat()

def to_berlin(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ)

# Minimal, extendable mapping of market suffix -> (tz, regular session start HH:MM)
_EXCHANGE_TZ_START: Dict[str, Tuple[str, time]] = {
    "US": ("America/New_York", time(9, 30)),
    "XETRA": ("Europe/Berlin", time(9, 0)),
    "DE": ("Europe/Berlin", time(9, 0)),  # Frankfurt/Deutsche Börse
    "F": ("Europe/Berlin", time(9, 0)),    # Frankfurt suffix .F
    "LSE": ("Europe/London", time(8, 0)),
    "L": ("Europe/London", time(8, 0)),    # London alt suffix .L
    "SIX": ("Europe/Zurich", time(9, 0)),
    "TSE": ("Asia/Tokyo", time(9, 0)),
    "T": ("Asia/Tokyo", time(9, 0)),       # Tokyo alt suffix .T
    "HK": ("Asia/Hong_Kong", time(9, 30)),
}

def _symbol_suffix(sym: str) -> str:
    s = (sym or "").strip().upper()
    if "." in s:
        return s.rsplit(".", 1)[-1]
    return "US"  # default

def _zoneinfo_safe(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        # Fallback to UTC if tzdata isn't available
        return ZoneInfo("UTC")

def _exchange_tz_and_start(sym: str) -> Tuple[ZoneInfo, time]:
    suf = _symbol_suffix(sym)
    entry = _EXCHANGE_TZ_START.get(suf) or _EXCHANGE_TZ_START.get(suf.upper())
    if not entry:
        # try mapping like XETRA, US etc if full suffix given
        entry = _EXCHANGE_TZ_START.get(suf.upper(), ("America/New_York", time(9,30)))
    tz = _zoneinfo_safe(entry[0])
    return tz, entry[1]

def classify_freshness(symbol: str, ts: datetime, flags: Dict[str, object] | None = None) -> Tuple[str, str]:
    """
    Return (label, note) such as ("Live", "During regular session") or ("Previous close", "End of day price").
    Rules:
    - Respect provider flags if present: delayed/eod => Previous close.
    - Otherwise: if provider's last-trade timestamp is on the current trading day in exchange TZ and
      the local wall clock is within or after regular session start, mark Live; else Previous close.
    """
    flags = flags or {}
    if bool(flags.get("eod") or flags.get("is_eod") or flags.get("delayed") or flags.get("is_delayed")):
        return "Previous close", "End of day price"

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    tz, start = _exchange_tz_and_start(symbol)
    now_local = datetime.now(tz)
    ts_local = ts.astimezone(tz)

    if ts_local.date() == now_local.date() and now_local.time() >= start:
        return "Live", "During regular session"
    return "Previous close", "Last trading day"
