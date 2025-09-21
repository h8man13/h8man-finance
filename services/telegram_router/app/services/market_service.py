from __future__ import annotations

from typing import Dict


_MARKET_MAPPING = {
    # US
    "US": "US",
    "NYSE": "NYS",
    "NASDAQ": "NAS",
    "NSDQ": "NAS",
    # Germany / Xetra
    "XETRA": "XET",
    "DE": "XET",
    "FWB": "XET",
    # UK
    "LSE": "LSE",
    "LON": "LSE",
    # Canada
    "TSX": "TSX",
    "TSXV": "TSV",
    # Japan
    "TSE": "TYO",
    "JPX": "TYO",
    # Australia
    "ASX": "ASX",
    # Switzerland
    "SIX": "SIX",
    "SWX": "SIX",
    # France / Euronext Paris
    "PAR": "PAR",
    "EPA": "PAR",
    # Netherlands / Euronext Amsterdam
    "AMS": "AMS",
    "AEX": "AMS",
    # Spain
    "BME": "MAD",
    "MCE": "MAD",
    # Hong Kong
    "HK": "HK",
    "HKEX": "HK",
    # Singapore
    "SGX": "SG",
}


def market_label(symbol: str, market_code: str) -> str:
    suffix = ""
    if "." in symbol:
        suffix = symbol.split(".")[-1].upper()
    code = (market_code or "").upper()
    for candidate in (suffix, code):
        if candidate and candidate in _MARKET_MAPPING:
            return _MARKET_MAPPING[candidate]
    return suffix or code or "-"


def freshness_label(raw: str) -> str:
    value = (raw or "").lower()
    if "live" in value:
        return "L"
    if "prev" in value:
        return "P"
    if "eod" in value or "end of day" in value:
        return "E"
    if "delay" in value:
        return "D"
    return value.upper()[:3] if value else "n/a"
