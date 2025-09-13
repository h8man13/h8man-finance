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
_EXCHANGE_TZ_HOURS: Dict[str, Tuple[str, time, time]] = {
    "US": ("America/New_York", time(9, 30), time(16, 0)),
    "XETRA": ("Europe/Berlin", time(9, 0), time(17, 30)),
    "DE": ("Europe/Berlin", time(9, 0), time(17, 30)),  # Frankfurt/Deutsche Börse
    "F": ("Europe/Berlin", time(9, 0), time(17, 30)),    # Frankfurt suffix .F
    "LSE": ("Europe/London", time(8, 0), time(16, 30)),
    "L": ("Europe/London", time(8, 0), time(16, 30)),    # London alt suffix .L
    "SIX": ("Europe/Zurich", time(9, 0), time(17, 30)),
    "TSE": ("Asia/Tokyo", time(9, 0), time(15, 0)),
    "T": ("Asia/Tokyo", time(9, 0), time(15, 0)),       # Tokyo alt suffix .T
    "HK": ("Asia/Hong_Kong", time(9, 30), time(16, 0)),
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

def _exchange_tz_and_hours(sym: str) -> Tuple[ZoneInfo, time, time]:
    suf = _symbol_suffix(sym)
    entry = _EXCHANGE_TZ_HOURS.get(suf) or _EXCHANGE_TZ_HOURS.get(suf.upper())
    if not entry:
        entry = _EXCHANGE_TZ_HOURS.get(suf.upper(), ("America/New_York", time(9, 30), time(16, 0)))
    tz = _zoneinfo_safe(entry[0])
    return tz, entry[1], entry[2]

_TZ_ABBR = {
    "America/New_York": "NY",
    "Europe/Berlin": "Berlin",
    "Europe/London": "London",
    "Asia/Tokyo": "Tokyo",
    "Asia/Hong_Kong": "HK",
    "Europe/Zurich": "Zurich",
}

def classify_freshness(symbol: str, ts: datetime, flags: Dict[str, object] | None = None) -> Tuple[str, str, str]:
    """
    Return (label, note) such as ("Live", "During regular session") or ("Previous close", "End of day price").
    Rules:
    - Respect provider flags if present: delayed/eod => Previous close.
    - Otherwise: if provider's last-trade timestamp is on the current trading day in exchange TZ and
      the local wall clock is within or after regular session start, mark Live; else Previous close.
    """
    flags = flags or {}
    if bool(flags.get("eod") or flags.get("is_eod") or flags.get("delayed") or flags.get("is_delayed")):
        tz, _, _ = _exchange_tz_and_hours(symbol)
        abbr = _TZ_ABBR.get(str(tz.key), "") if hasattr(tz, "key") else ""
        label = (abbr + " EOD").strip()
        return "Previous close", "End of day price", label

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    tz, start, end = _exchange_tz_and_hours(symbol)
    now_local = datetime.now(tz)
    ts_local = ts.astimezone(tz)

    abbr = _TZ_ABBR.get(str(tz.key), "") if hasattr(tz, "key") else ""
    # Same trading day
    if ts_local.date() == now_local.date():
        if start <= now_local.time() <= end:
            tlabel = f"{abbr} {ts_local.strftime('%H:%M')}".strip()
            return "Live", "During regular session", tlabel
        # Outside session hours on same day
        tlabel = f"{abbr} {ts_local.strftime('%H:%M')}".strip()
        return "Market closed", "Outside regular session", tlabel
    # Different day -> previous close
    return "Previous close", "Last trading day", (abbr + " EOD").strip()
