from __future__ import annotations

from pathlib import Path

from MK4.app.server import _render_ui_html


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"


def test_ui_injects_local_markdown_assets_after_existing_inline_script() -> None:
    html = _render_ui_html()

    assert '<link rel="stylesheet" href="/static/markdown-render.css" />' in html
    assert '<script src="/static/markdown-render.js"></script>' in html
    assert html.index("/static/markdown-render.css") < html.index("</head>")
    assert html.index("function renderMessageText") < html.index("/static/markdown-render.js")
    assert "cdn.jsdelivr.net" not in html
    assert "unpkg.com" not in html


def test_markdown_renderer_escapes_html_and_supports_expected_blocks() -> None:
    source = (STATIC_DIR / "markdown-render.js").read_text(encoding="utf-8")

    assert 'replace(/</g, "&lt;")' in source
    assert 'replace(/>/g, "&gt;")' in source
    assert "const heading = line.match" in source
    assert "const unordered = line.match" in source
    assert "const ordered = line.match" in source
    assert "const quote = line.match" in source
    assert "<pre><code" in source
    assert "<strong>" in source
    assert "<em>" in source
    assert 'window.renderMessageText = renderMarkdown' in source


def test_inline_placeholders_cannot_be_reinterpreted_as_markdown_emphasis() -> None:
    source = (STATIC_DIR / "markdown-render.js").read_text(encoding="utf-8")

    # The old @@CODE_0@@ / @@LINK_0@@ placeholders contained underscores. The
    # italic parser could consume those underscores and leave visible artifacts
    # such as @@CODE*0@@ in the rendered answer.
    assert "@@CODE_" not in source
    assert "@@LINK_" not in source
    assert 'const TOKEN_START = "\\uE000"' in source
    assert 'const TOKEN_END = "\\uE001"' in source
    assert 'placeholder("C", codeTokens.length)' in source
    assert 'placeholder("L", linkTokens.length)' in source
    assert 'restorePlaceholders(text, "C", codeTokens)' in source
    assert 'restorePlaceholders(text, "L", linkTokens)' in source


def test_markdown_styles_are_scoped_to_assistant_bubbles() -> None:
    css = (STATIC_DIR / "markdown-render.css").read_text(encoding="utf-8")

    assert ".msg-row.MK4 .bubble-text" in css
    assert ".msg-row.user" not in css
    assert "h1 { font-size" in css
    assert "pre code" in css
