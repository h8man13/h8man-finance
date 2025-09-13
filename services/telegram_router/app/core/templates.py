from __future__ import annotations

from typing import List
import re

from babel.numbers import format_currency


# Telegram MarkdownV2 escaping: avoid escaping '.' to keep numbers readable
# Also leave '-' unescaped for readability
# Full MarkdownV2 escape set outside entities per Telegram spec
MDV2_ESCAPE_CHARS = set("_*[]()~`>#+-=|{}.!")


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


def mdv2_blockquote(lines: List[str], *, exclude_escape: set[str] | None = None) -> str:
    """Build a MarkdownV2 blockquote from content lines.
    Each content line is escaped per MDV2 and prefixed with '>'.
    """
    exclude_escape = exclude_escape or set()
    def _esc(s: str) -> str:
        # Escape per MDV2 but allow certain characters to remain unescaped
        out = []
        for ch in s:
            if ch in MDV2_ESCAPE_CHARS and ch not in exclude_escape:
                out.append("\\" + ch)
            else:
                out.append(ch)
        return "".join(out)
    out = []
    for ln in lines:
        out.append(">" + _esc(ln))
    return "\n".join(out)


def mdv2_expandable_blockquote(intro_lines: List[str], expanded_lines: List[str]) -> str:
    """
    Build an expandable blockquote per Telegram MarkdownV2 trick:
    - A normal blockquote section
    - A bold-empty separator line '**'
    - A second blockquote section; ensure last line ends with '||'
    """
    top = mdv2_blockquote(intro_lines)
    # Ensure last expanded line has '||'
    exp_lines = list(expanded_lines)
    if exp_lines:
        if not str(exp_lines[-1]).endswith("||"):
            exp_lines[-1] = str(exp_lines[-1]) + "||"
    # Do not escape '|' so the '||' marker remains intact for Telegram
    bottom = mdv2_blockquote(exp_lines, exclude_escape={"|"})
    return f"{top}\n**\n{bottom}"


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
            # Parse blockquotes and expandable separator '**' on raw seg, then format
            raw_lines = seg.splitlines()
            blocks: List[dict] = []  # {type: 'quote'|'text', lines: [...], expandable: bool}
            cur: List[str] = []
            in_quote = False
            expandable_next = False
            def push_cur():
                nonlocal cur, in_quote, expandable_next
                if not cur:
                    return
                if in_quote:
                    blocks.append({"type": "quote", "lines": cur[:], "expandable": expandable_next})
                    expandable_next = False
                else:
                    blocks.append({"type": "text", "lines": cur[:]})
                cur = []
            for ln in raw_lines:
                if ln.strip() == "**":
                    push_cur()
                    in_quote = False
                    expandable_next = True  # next quote block becomes expandable
                    continue
                if ln.startswith(">"):
                    if not in_quote:
                        push_cur()
                        in_quote = True
                    cur.append(ln.lstrip(">"))
                else:
                    if in_quote:
                        push_cur()
                        in_quote = False
                    cur.append(ln)
            push_cur()

            def fmt_inline(t: str) -> str:
                s = _html_escape(t)
                s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
                s = re.sub(r"__([^_]+)__", r"<u>\1</u>", s)
                s = re.sub(r"~([^~]+)~", r"<s>\1</s>", s)
                s = re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", s)
                s = re.sub(r"\*(.+?)\*", r"<b>\1</b>", s)
                s = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", s)
                s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f"<a href=\"{_html_escape(m.group(2))}\">{m.group(1)}</a>", s)
                return s

            for b in blocks:
                if b["type"] == "quote":
                    # For expandable quotes, strip trailing '||' marker from last line
                    lines_q = list(b["lines"]) if b["lines"] else []
                    if b.get("expandable") and lines_q:
                        if str(lines_q[-1]).endswith("||"):
                            lines_q[-1] = str(lines_q[-1])[:-2]
                    content = "\n".join(fmt_inline(x) for x in lines_q).strip("\n")
                    if b.get("expandable"):
                        out.append(f"<blockquote expandable>{content}</blockquote>")
                    else:
                        out.append(f"<blockquote>{content}</blockquote>")
                else:
                    out.append("\n".join(fmt_inline(x) for x in b["lines"]))
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
