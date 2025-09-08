from typing import Tuple

def normalize_symbol(sym: str) -> str:
    """
    Public facing normalization.
    - Keep crypto pairs like BTC-USD unchanged.
    - Attach .US to bare symbols without a market suffix.
    """
    s = sym.strip().upper()
    if "-" in s:  # crypto like BTC-USD
        return s
    if "." not in s:
        s = f"{s}.US"
    return s

def infer_market_currency(sym: str) -> Tuple[str, str]:
    """
    Infer (market, currency) for a normalized symbol.
    - Crypto pairs are considered USD at source.
    - .XETRA is EUR.
    - Default to US, USD.
    """
    s = sym.strip().upper()
    if "-" in s:
        return ("CRYPTO", "USD")  # per spec
    if s.endswith(".XETRA"):
        return ("XETRA", "EUR")
    return ("US", "USD")

def eodhd_code_from_symbol(sym: str) -> str:
    """
    Map a client symbol to the upstream EODHD code.
    - Crypto pairs (A-B) must carry the .CC suffix for EODHD.
    - Other symbols pass through unchanged.
    No hardcoded lists, generic rule only.
    """
    s = sym.strip().upper()
    if "-" in s and not s.endswith(".CC"):
        return f"{s}.CC"
    return s
