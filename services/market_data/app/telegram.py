import base64
import hmac
import hashlib
import os
from typing import Dict, Iterable

try:
    from nacl.signing import VerifyKey  # type: ignore
    _HAS_NACL = True
except Exception:  # pragma: no cover
    _HAS_NACL = False


TG_PUBKEY_PROD_HEX = "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"
TG_PUBKEY_TEST_HEX = "40055058a4ee38156a06562e52eece92a771bcd8346a8c4615cb7376eddf72ec"


def data_check_string_from_pairs_sorted(pairs: Dict[str, str]) -> str:
    filtered = {k: v for k, v in pairs.items() if k not in ("hash", "signature")}
    return "\n".join(f"{k}={filtered[k]}" for k in sorted(filtered.keys()))


def data_check_string_from_pairs_original(raw_qs: str) -> str:
    parts = []
    for part in raw_qs.split("&"):
        if not part:
            continue
        k, v = (part.split("=", 1) + [""])[:2]
        if k in ("hash", "signature"):
            continue
        parts.append(f"{k}={v}")
    return "\n".join(parts)


def _hmac_webappdata_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def compute_sig_hex(dcs: str, key_bytes: bytes) -> str:
    return hmac.new(key_bytes, msg=dcs.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()


def signature_variants(decoded_pairs: Dict[str, str], raw_qs: str, bot_token: str) -> Iterable[str]:
    keys = [_hmac_webappdata_key(bot_token)]
    d_sorted = data_check_string_from_pairs_sorted(decoded_pairs)
    d_original = data_check_string_from_pairs_original(raw_qs)

    tokens = [bot_token]
    t_strip = bot_token.strip()
    if t_strip != bot_token:
        tokens.append(t_strip)

    seen = set()
    for t in tokens:
        k = _hmac_webappdata_key(t)
        for dcs in (d_sorted, d_original):
            try:
                h = compute_sig_hex(dcs, k).lower()
                if h not in seen:
                    seen.add(h)
                    yield h
            except Exception:
                continue


def verify_ed25519(pairs: Dict[str, str], bot_token: str) -> bool:
    if not _HAS_NACL:
        return False
    sig_b64 = pairs.get("signature") or ""
    if not sig_b64:
        return False
    bot_id = (bot_token.split(":", 1)[0] if bot_token else "").strip()
    msg = f"{bot_id}:WebAppData\n{data_check_string_from_pairs_sorted(pairs)}"
    pad = "=" * (-len(sig_b64) % 4)
    try:
        sig = base64.b64decode(sig_b64 + pad)
    except Exception:
        return False
    use_test = str(os.getenv("TG_USE_TEST_PUBKEY", "false")).lower() in ("1", "true", "yes", "y")
    pub_hex = TG_PUBKEY_TEST_HEX if use_test else TG_PUBKEY_PROD_HEX
    try:
        vk = VerifyKey(bytes.fromhex(pub_hex))
        vk.verify(msg.encode("utf-8"), sig)
        return True
    except Exception:
        return False

