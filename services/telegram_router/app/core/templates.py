from __future__ import annotations

from typing import List

from babel.numbers import format_currency


MDV2_ESCAPE_CHARS = set("_[]()~`>#+-=|{}.!")


def escape_mdv2(s: str) -> str:
    out = []
    for ch in s:
        if ch in MDV2_ESCAPE_CHARS:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def bold(s: str) -> str:
    return f"*{escape_mdv2(s)}*"


def italic(s: str) -> str:
    return f"_{escape_mdv2(s)}_"


def code(s: str) -> str:
    return f"`{s}`"


def monotable(rows: List[List[str]]) -> str:
    # Render rows as monospaced table in triple backticks
    col_widths = []
    for row in rows:
        for i, cell in enumerate(row):
            if i >= len(col_widths):
                col_widths.append(len(cell))
            else:
                col_widths[i] = max(col_widths[i], len(cell))
    lines = []
    for row in rows:
        padded = [cell.ljust(col_widths[i]) for i, cell in enumerate(row)]
        lines.append(" ".join(padded))
    body = "\n".join(lines)
    return f"```\n{body}\n```"


def euro(n: float) -> str:
    try:
        return format_currency(n, "EUR", locale="de_DE")
    except Exception:
        return f"€{n:.2f}"


def paginate(text: str, limit: int = 4096) -> List[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        chunks.append(text[start:end])
        start = end
    return chunks

