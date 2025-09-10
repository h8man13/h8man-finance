from __future__ import annotations

import shlex
from typing import List, Optional, Tuple


def normalize_command(raw: str, bot_username: Optional[str] = None) -> str:
    s = raw.strip()
    if not s:
        return s
    if s.startswith("/"):
        s = s[1:]
    # strip @botusername
    if "@" in s:
        cmd, _, at = s.partition("@")
        if bot_username and at.lower() == bot_username.lower():
            s = cmd
        else:
            s = cmd  # ignore any @target
    return "/" + s.lower()


def tokenize_args(text: str) -> List[str]:
    # supports quotes and multiple spaces
    try:
        return [t for t in shlex.split(text)]
    except Exception:
        return [p for p in text.strip().split() if p]


def parse_text(text: str, bot_username: Optional[str] = None) -> Tuple[Optional[str], List[str]]:
    text = (text or "").strip()
    if not text:
        return None, []
    parts = text.split(maxsplit=1)
    first = parts[0]
    if not first.startswith("/"):
        return None, tokenize_args(text)
    cmd = normalize_command(first, bot_username)
    rest = parts[1] if len(parts) > 1 else ""
    args = tokenize_args(rest)
    return cmd, args

