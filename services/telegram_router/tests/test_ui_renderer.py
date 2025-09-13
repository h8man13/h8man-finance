def test_ui_renderer_basic_blocks():
    from app.ui.renderer import render_blocks  # type: ignore

    blocks = [
        {"header": "Title"},
        {"paragraph": "Hello (world)"},
        {"bullets": {"items": ["Item one", "Item two"]}},
        {"code": "print('hi')"},
        {"footnote": "Note: Be nice."},
    ]
    out = render_blocks(blocks)
    # Header bold, not underline
    assert out.startswith("*Title*")
    # Paragraph escaped parentheses
    assert r"Hello \(world\)" in out
    # Bullet prefix
    assert "• Item one" in out and "• Item two" in out
    # Code fenced and preserved
    assert "```" in out and "print('hi')" in out
    # Footnote italic with one blank line padding
    assert "_Note: Be nice._" in out

def test_ui_loader_includes(monkeypatch, tmp_path):
    from app.ui.loader import load_ui, render_screen  # type: ignore
    import os

    ui_yaml = tmp_path / "ui.yml"
    ui_yaml.write_text(
        """
snippets:
  s1:
    - paragraph: "Hello {name}"

screens:
  home:
    blocks:
      - include: s1
      - paragraph: "Bye"
        
""",
        encoding="utf-8",
    )
    ui = load_ui(str(ui_yaml))
    pages = render_screen(ui, "home", {"name": "Ada"})
    assert pages and "Hello Ada" in pages[0] and "Bye" in pages[0]

