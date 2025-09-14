from typing import Tuple

def normalize_symbol(sym: str) -> str:
    """
    Public-facing normalization.
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
    - EUR markets (no USD->EUR FX applied): .XETRA, .F, .AS, .PA, .BR, .LS, .MI, .MC, .HE
    - Default to US, USD.
    """
    s = sym.strip().upper()
    if "-" in s:
        return ("CRYPTO", "USD")

    # Treat these exchanges as EUR-denominated like XETRA
    eur_suffixes = [
        ".XETRA",
        ".F",   # Frankfurt
        ".AS",  # Amsterdam
        ".PA",  # Paris
        ".BR",  # Brussels
        ".LS",  # Lisbon
        ".MI",  # Milan
        ".MC",  # Madrid
        ".HE",  # Helsinki
    ]

    for suf in eur_suffixes:
        if s.endswith(suf):
            market = "XETRA" if suf == ".XETRA" else suf.lstrip(".")
            return (market, "EUR")

    return ("US", "USD")

def eodhd_code_from_symbol(sym: str) -> str:
    """
    Map a client symbol to the upstream EODHD code.
    - Crypto pairs (A-B) need the .CC suffix for EODHD.
    - Other symbols pass through unchanged.
    No hardcoded lists; generic rule only.
    """
    s = sym.strip().upper()
    if "-" in s and not s.endswith(".CC"):
        return f"{s}.CC"
    return s
