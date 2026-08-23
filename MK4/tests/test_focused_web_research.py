from __future__ import annotations

import pytest

from MK4.tools import focused_web_search
from MK4.tools.focused_web_search import FocusedWebSearchTool, _FocusedReadableHtmlParser
from MK4.tools.web_search import SearchHit


@pytest.mark.asyncio
async def test_web_research_uses_one_query_matching_language_wiki_and_three_distinct_pages(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_ddg(query: str):
        calls.append(("ddg", query))
        return [
            SearchHit(title="A", url="https://example.com/a", snippet="대한민국 대통령 이재명", source="duckduckgo"),
            SearchHit(title="B", url="https://example.com/b", snippet="대한민국 대통령", source="duckduckgo"),
            SearchHit(title="C", url="https://example.com/c", snippet="대한민국 대통령", source="duckduckgo"),
        ]

    async def fake_wiki(query: str, language: str):
        calls.append((f"wiki:{language}", query))
        return [
            SearchHit(title="대한민국 대통령", url="https://ko.wikipedia.org/wiki/대한민국_대통령", snippet="대한민국 대통령", source="wikipedia_ko"),
        ]

    read_urls: list[str] = []

    async def fake_page_read(self, arguments: dict):
        url = arguments["url"]
        read_urls.append(url)
        return {
            "ok": True,
            "url": url,
            "title": url.rsplit("/", 1)[-1],
            "matched_sections": ["evidence"],
            "content": "evidence",
            "truncated": False,
        }

    monkeypatch.setattr(focused_web_search, "_ddg_search", fake_ddg)
    monkeypatch.setattr(focused_web_search, "_wiki_search", fake_wiki)
    monkeypatch.setattr(FocusedWebSearchTool, "_run_page_read", fake_page_read)

    tool = FocusedWebSearchTool()
    result = await tool._run_research(
        {
            "objective": "현재 대한민국의 대통령 이름",
            "language": "ko",
            "preferred_domains": [],
        }
    )

    assert calls == [
        ("ddg", "현재 대한민국의 대통령 이름"),
        ("wiki:ko", "현재 대한민국의 대통령 이름"),
    ]
    assert result["queries"] == ["현재 대한민국의 대통령 이름"]
    assert result["language"] == "ko"
    assert len(read_urls) == 3
    assert len(set(read_urls)) == 3


def test_web_research_schema_requires_model_supplied_language_and_single_query_contract():
    registry = FocusedWebSearchTool().build_registry()
    definition = registry.definition("web_research")

    assert definition is not None
    assert definition.input_schema["required"] == ["objective", "language"]
    assert "language" in definition.input_schema["properties"]
    assert "additional query" in definition.description.lower()


@pytest.mark.asyncio
async def test_web_research_rejects_missing_language_without_guessing():
    tool = FocusedWebSearchTool()

    with pytest.raises(ValueError, match="language"):
        await tool._run_research({"objective": "current president of South Korea"})


def test_html_parser_prefers_main_and_excludes_page_chrome_and_related_articles():
    parser = _FocusedReadableHtmlParser()
    parser.feed(
        """
        <html>
          <head><title>Example News</title></head>
          <body>
            <header>site header</header>
            <nav>home politics culture</nav>
            <main>
              <article>
                <h1>Bushcraft guide</h1>
                <p>main article paragraph one</p>
                <aside>recommended links inside main</aside>
                <p>main article paragraph two</p>
              </article>
            </main>
            <article><h2>related article</h2><p>unrelated recommendation</p></article>
            <footer>copyright and contact</footer>
          </body>
        </html>
        """
    )

    content = parser.text()
    assert parser.title == "Example News"
    assert "Bushcraft guide" in content
    assert "main article paragraph one" in content
    assert "main article paragraph two" in content
    assert "site header" not in content
    assert "home politics culture" not in content
    assert "recommended links inside main" not in content
    assert "related article" not in content
    assert "unrelated recommendation" not in content
    assert "copyright and contact" not in content


def test_html_parser_uses_article_when_main_is_absent():
    parser = _FocusedReadableHtmlParser()
    parser.feed(
        """
        <body>
          <header>site header</header>
          <article>
            <h1>Primary article</h1>
            <p>article body</p>
          </article>
          <aside>sidebar recommendation</aside>
          <footer>footer text</footer>
        </body>
        """
    )

    assert parser.text() == "Primary article\narticle body"


def test_html_parser_falls_back_to_readable_text_without_main_or_article():
    parser = _FocusedReadableHtmlParser()
    parser.feed(
        """
        <body>
          <nav>navigation</nav>
          <div><h1>Legacy page</h1><p>useful legacy content</p></div>
          <footer>footer text</footer>
        </body>
        """
    )

    content = parser.text()
    assert "Legacy page" in content
    assert "useful legacy content" in content
    assert "navigation" not in content
    assert "footer text" not in content
