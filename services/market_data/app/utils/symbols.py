from typing import Tuple

def normalize_symbol(sym: str) -> str:
    s = sym.strip().upper()
    if "-" in s:  # crypto like BTC-USD
        return s
    if "." not in s:
        s = f"{s}.US"
    return s

def infer_market_currency(sym: str) -> Tuple[str, str]:
    # returns (market, currency)
    if "-" in sym:
        return ("CRYPTO","USD")  # per spec
    if sym.endswith(".XETRA"):
        return ("XETRA","EUR")
    return ("US","USD")
