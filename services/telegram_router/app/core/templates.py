from __future__ import annotations

from typing import List
import re

from babel.numbers import format_currency


# Telegram MarkdownV2 escaping: avoid escaping '.' to keep numbers readable
# Also leave '-' unescaped for readability
MDV2_ESCAPE_CHARS = set("_[]()~`>#+=|{}!")


def escape_mdv2(s: str) -> str:
    out = []
    for ch in s:
        if ch in MDV2_ESCAPE_CHARS:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


STRICT_ESCAPE_CHARS = set("_[]()~`>#+-=|{}!.\\")  # includes '-' '.' and backslash


def escape_mdv2_strict(s: str) -> str:
    out = []
    for ch in s:
        if ch in STRICT_ESCAPE_CHARS:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def safe_escape_mdv2_with_fences(text: str, strict: bool = False) -> str:
    """Escape only outside of triple backtick blocks. When strict=True, escape a wider set."""
    parts = text.split("```")
    out_parts: List[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # inside code fence
            out_parts.append("```" + part + "```")
        else:
            esc = escape_mdv2_strict(part) if strict else escape_mdv2(part)
            out_parts.append(esc)
    return "".join(out_parts)


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def convert_markdown_to_html(text: str) -> str:
    """
    Convert our limited MarkdownV2 subset into equivalent HTML for Telegram fallback:
    - ```code blocks``` -> <pre>code blocks</pre>
    - *bold* -> <b>bold</b>
    - _italic_ -> <i>italic</i>
    - `code` -> <code>code</code>
    Other content is left as-is; this function avoids escaping HTML special chars because Telegram expects plain text except tags.
    """
    # Convert fenced code blocks first
    segments = text.split("```")
    out: List[str] = []
    for i, seg in enumerate(segments):
        if i % 2 == 1:
            # Handle optional language prefix on first line
            lang = None
            if "\n" in seg:
                first, rest = seg.split("\n", 1)
                if re.fullmatch(r"[A-Za-z0-9_\-]+", first.strip()):
                    lang = first.strip()
                    code = rest
                else:
                    code = seg
            else:
                code = seg
            code_esc = _html_escape(code)
            if lang:
                out.append(f"<pre><code class=\"language-{lang}\">{code_esc}</code></pre>")
            else:
                out.append(f"<pre>{code_esc}</pre>")
        else:
            # Escape basic HTML first
            s = _html_escape(seg)
            # inline code
            s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
            # underline, strike, spoiler (MDV2 variants)
            s = re.sub(r"__([^_]+)__", r"<u>\1</u>", s)
            s = re.sub(r"~([^~]+)~", r"<s>\1</s>", s)
            s = re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", s)
            # bold and italic (non-greedy)
            s = re.sub(r"\*(.+?)\*", r"<b>\1</b>", s)
            # avoid matching double-underscore underline
            s = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", s)
            # inline links [text](url)
            s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f"<a href=\"{_html_escape(m.group(2))}\">{m.group(1)}</a>", s)
            # blockquotes starting with '>' lines -> <blockquote>
            lines = s.splitlines()
            out_lines: List[str] = []
            block: List[str] = []
            def flush_block():
                nonlocal out_lines, block
                if block:
                    out_lines.append("<blockquote>" + "\\n".join(block) + "</blockquote>")
                    block = []
            for ln in lines:
                if ln.startswith(">"):
                    block.append(ln.lstrip(">"))
                else:
                    flush_block()
                    out_lines.append(ln)
            flush_block()
            out.append("\n".join(out_lines))
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
