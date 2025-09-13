def test_safe_escape_mdv2_with_fences_preserves_code_blocks():
    from app.core.templates import safe_escape_mdv2_with_fences  # type: ignore

    text = "outside (paren) and _underline_\n```\nA_B-C.D\n```\nmore + text"
    out = safe_escape_mdv2_with_fences(text)

    # outside text: parentheses and underscores are escaped
    assert r"outside \(paren\) and \_underline\_" in out
    # code fence preserved and content inside not escaped
    assert "```" in out
    assert "A_B-C.D" in out  # no extra backslashes inside code block


def test_safe_escape_mdv2_with_fences_strict_escapes_broadly():
    from app.core.templates import safe_escape_mdv2_with_fences  # type: ignore

    text = r"dash- dot. back\slash"
    out = safe_escape_mdv2_with_fences(text, strict=True)
    # strict mode escapes '-' and '.' and backslash
    assert "dash\\- dot\\. back\\\\slash" in out


def test_convert_markdown_to_html_basic():
    from app.core.templates import convert_markdown_to_html  # type: ignore

    md = "This is *bold* and _ital_ and `code`.\n```\nline1\nline2\n```\nend"
    html = convert_markdown_to_html(md)
    assert "<b>bold</b>" in html
    assert "<i>ital</i>" in html
    assert "<code>code</code>" in html
    # Accept with or without extra newlines inside <pre>
    assert "<pre>" in html and "line1\nline2" in html and "</pre>" in html


def test_convert_markdown_to_html_expandable():
    from app.core.templates import convert_markdown_to_html  # type: ignore

    md = ">Intro line\n**\n>Hidden part line\n>Last line||"
    html = convert_markdown_to_html(md)
    assert "<blockquote>Intro line</blockquote>" in html
    assert "<blockquote expandable>Hidden part line\nLast line</blockquote>" in html


def test_mdv2_blockquote_and_expandable_builders():
    from app.core.templates import mdv2_blockquote, mdv2_expandable_blockquote  # type: ignore

    bq = mdv2_blockquote(["Hello (world)"])
    assert bq.startswith(">") and r"\(world\)" in bq

    exp = mdv2_expandable_blockquote(["Top"], ["Hidden A", "Hidden B"])
    # Contains bold-empty separator and blockquote markers
    assert "\n**\n" in exp
    assert exp.count(">") >= 3
    assert exp.endswith("Hidden B||")
