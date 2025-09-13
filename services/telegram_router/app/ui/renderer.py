from __future__ import annotations

from typing import Any, Dict, List

from ..core.templates import escape_mdv2, escape_mdv2_preserving_code, monotable, mdv2_blockquote, paginate


def _blank_line(buf: List[str]):
    if buf and buf[-1] != "":
        buf.append("")


def _fmt(text: str, data: Dict[str, Any]) -> str:
    try:
        return str(text).format(**data)
    except Exception:
        return str(text)


def render_blocks(blocks: List[Dict[str, Any]], *, data: Dict[str, Any] | None = None, strict: bool = False) -> str:
    """
    Render a list of UI blocks into Telegram MarkdownV2-safe text.
    Atoms supported: header, subheader, paragraph, pattern, code, table, bullets, footnote, quote, divider, spacer.
    Applies escaping outside of code blocks, with consistent spacing rules.
    """
    data = data or {}
    out: List[str] = []

    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        # Normalize single-key mapping like {"header": "Text"} to {type: 'header', text: 'Text'}
        if len(block.keys()) == 1 and next(iter(block.keys())) not in ("type", "include"):
            k = next(iter(block.keys()))
            v = block[k]
            # Expand shorthand forms like {"header": "Text"} or {"table": {rows: ...}}
            if isinstance(v, dict):
                b = {"type": k}
                b.update(v)
                block = b
            elif isinstance(v, list):
                if k == "quote":
                    block = {"type": "quote", "lines": v}
                elif k == "bullets":
                    block = {"type": "bullets", "items": v}
                elif k == "table":
                    block = {"type": "table", "rows": v}
                else:
                    block = {"type": k, "text": "\n".join(str(x) for x in v)}
            else:
                block = {"type": k, "text": str(v)}

        btype = str(block.get("type") or next((k for k in block.keys() if k not in ("include",)), "")).lower()

        if btype == "header":
            text = _fmt(block.get("text", ""), data)
            if text:
                out.append(f"*{escape_mdv2(text)}*")
                _blank_line(out)
            continue

        if btype == "subheader":
            text = _fmt(block.get("text", ""), data)
            if text:
                out.append(f"*{escape_mdv2(text)}*")
            continue

        if btype == "paragraph":
            text = _fmt(block.get("text", ""), data)
            if text:
                out.append(escape_mdv2_preserving_code(text))
            continue

        if btype == "pattern":
            text = _fmt(block.get("text", ""), data)
            if text:
                out.append(f"`{text}`")
            continue

        if btype == "code":
            text = _fmt(block.get("text", ""), data)
            _blank_line(out)
            out.append(f"```\n{text}\n```")
            _blank_line(out)
            continue

        if btype == "table":
            rows = block.get("rows")
            # Support variable indirection: "table_rows" or "{table_rows}"
            if isinstance(rows, str):
                key = rows.strip()
                if key.startswith("{") and key.endswith("}"):
                    key = key[1:-1]
                rows = data.get(key, rows)
            if isinstance(rows, list) and rows:
                _blank_line(out)
                out.append(monotable([[str(c) for c in r] for r in rows]))
                _blank_line(out)
            continue

        if btype == "bullets":
            items = block.get("items") or []
            # Support variable list indirection: "items": "list_key" or "{list_key}"
            if isinstance(items, str):
                key = items.strip()
                if key.startswith("{") and key.endswith("}"):
                    key = key[1:-1]
                value = data.get(key)
                if isinstance(value, list):
                    items = value
                else:
                    items = [items]
            for it in items:
                itxt = _fmt(str(it), data)
                out.append(f"• {escape_mdv2_preserving_code(itxt)}")
            continue

        if btype == "footnote":
            text = _fmt(block.get("text", ""), data)
            _blank_line(out)
            out.append(f"_{escape_mdv2_preserving_code(text)}_")
            _blank_line(out)
            continue

        if btype == "quote":
            lines = block.get("lines") or []
            lines = [_fmt(str(x), data) for x in lines]
            out.append(mdv2_blockquote(lines))
            continue

        if btype == "divider":
            _blank_line(out)
            continue

        if btype == "spacer":
            n = int(block.get("lines", 1))
            for _ in range(max(1, n)):
                out.append("")
            continue

        # Unknown: ignore

    # Cleanup leading/trailing blank lines and compress consecutive blanks to single
    cleaned: List[str] = []
    prev_blank = False
    for part in out:
        is_blank = (part.strip() == "")
        if is_blank and prev_blank:
            continue
        cleaned.append(part)
        prev_blank = is_blank
    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned)


def paginate_blocks(blocks: List[Dict[str, Any]], *, data: Dict[str, Any] | None = None) -> List[str]:
    text = render_blocks(blocks, data=data)
    return paginate(text)
