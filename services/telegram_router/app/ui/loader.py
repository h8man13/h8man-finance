from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List
import os
import yaml

from .renderer import paginate_blocks


@lru_cache(maxsize=1)
def load_ui(path: str) -> Dict[str, Any] | None:
    p = (path or "").strip()
    if not p:
        return None
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _expand_includes(blocks: List[Dict[str, Any]], ui: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    snippets = (ui or {}).get("snippets", {}) or {}
    for b in blocks or []:
        if isinstance(b, dict) and "include" in b:
            name = b.get("include")
            sub = snippets.get(name)
            if isinstance(sub, list):
                out.extend(_expand_includes(sub, ui))
            continue
        out.append(b)
    return out


def render_screen(ui: Dict[str, Any] | None, key: str, data: Dict[str, Any]) -> List[str] | None:
    if not ui:
        return None
    scr = ((ui.get("screens", {}) or {}).get(key) or {}) if isinstance(ui, dict) else {}
    blocks = (scr or {}).get("blocks")
    if not isinstance(blocks, list):
        return None
    blocks = _expand_includes(blocks, ui)
    return paginate_blocks(blocks, data=data)

