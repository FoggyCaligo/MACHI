from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from html.parser import HTMLParser
from typing import Any

from .tool_runtime import ToolDefinition, ToolRegistry
from .web_search import (
    HttpWebSearchTool,
    SearchHit,
    _MAX_PAGE_CHARS,
    _clean_domains,
    _ddg_search,
    _error_summary,
    _fetch_public_page,
    _focused_passages,
    _objective_terms,
    _rank_research_results,
    _wiki_search,
)


_LANGUAGE_RE = re.compile(r"^[a-z][a-z0-9-]{1,11}$")


class _FocusedReadableHtmlParser(HTMLParser):
    """Extract readable page text using HTML structure rather than text heuristics.

    Semantic ``main`` content has highest priority, then ``article`` content, then
    the broad readable-text fallback. Explicit non-content regions such as
    navigation, footers and sidebars are ignored at every level.
    """

    _SKIP_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "template",
        "nav",
        "footer",
        "aside",
        "form",
        "dialog",
        "menu",
        "iframe",
    }
    _BLOCK_TAGS = {
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._main_depth = 0
        self._article_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._fallback_parts: list[str] = []
        self._main_parts: list[str] = []
        self._article_parts: list[str] = []

    @property
    def title(self) -> str:
        return " ".join(" ".join(self._title_parts).split())

    def _append_boundary(self) -> None:
        self._fallback_parts.append("\n")
        if self._main_depth > 0:
            self._main_parts.append("\n")
        if self._article_depth > 0:
            self._article_parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = True

        if lowered in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        if lowered == "main":
            self._main_depth += 1
        if lowered == "article":
            self._article_depth += 1
        if lowered in self._BLOCK_TAGS:
            self._append_boundary()

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = False

        if lowered in self._SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return

        if lowered in self._BLOCK_TAGS:
            self._append_boundary()
        if lowered == "main" and self._main_depth > 0:
            self._main_depth -= 1
        if lowered == "article" and self._article_depth > 0:
            self._article_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._skip_depth > 0:
            return
        self._fallback_parts.append(data)
        if self._main_depth > 0:
            self._main_parts.append(data)
        if self._article_depth > 0:
            self._article_parts.append(data)

    @staticmethod
    def _normalize(parts: list[str]) -> str:
        lines = [" ".join(line.split()) for line in "".join(parts).splitlines()]
        return "\n".join(line for line in lines if line)

    def text(self) -> str:
        main = self._normalize(self._main_parts)
        if main:
            return main
        article = self._normalize(self._article_parts)
        if article:
            return article
        return self._normalize(self._fallback_parts)


class FocusedWebSearchTool(HttpWebSearchTool):
    """Keep web_research focused on one model-supplied query.

    The model chooses the exact research objective/query and its language. This
    tool searches that one query across independent sources, reads three distinct
    result pages, and returns evidence. It does not invent follow-up queries.
    """

    def build_registry(self) -> ToolRegistry:
        registry = super().build_registry()
        registry.register(
            ToolDefinition(
                name="web_research",
                description=(
                    "Research one model-supplied public-web query end-to-end. Search the exact objective across "
                    "independent sources, use the matching-language Wikipedia edition, rank results, read three "
                    "distinct public pages, and return a compact evidence package. Do not use this tool to fan out "
                    "into multiple internally generated queries. If another search is needed, call web_research again "
                    "with that additional query."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "objective": {
                            "type": "string",
                            "description": (
                                "The single exact search objective/query to investigate now. Include the subject and "
                                "needed disambiguating context. Do not bundle several alternative queries together."
                            ),
                        },
                        "language": {
                            "type": "string",
                            "description": (
                                "Wikipedia language/subdomain matching the objective language, such as 'ko', 'en', "
                                "or 'ja'. Choose this from the query language; the tool will not guess it from text."
                            ),
                            "pattern": "^[a-z][a-z0-9-]{1,11}$",
                        },
                        "preferred_domains": {
                            "type": "array",
                            "description": (
                                "Optional preferred public domains used only for result ranking. They do not create "
                                "additional search queries."
                            ),
                            "items": {"type": "string"},
                            "maxItems": 4,
                        },
                    },
                    "required": ["objective", "language"],
                    "additionalProperties": False,
                },
            ),
            self._run_research,
        )
        return registry

    async def _run_page_read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = str(arguments.get("url") or "").strip()
        if not url:
            raise ValueError("web_page_read requires url")
        focus = [
            str(item).strip()
            for item in arguments.get("focus", [])
            if str(item).strip()
        ][:8]
        final_url, content_type, html = await _fetch_public_page(url)
        parser = _FocusedReadableHtmlParser()
        parser.feed(html)
        content = parser.text()
        return {
            "ok": True,
            "url": final_url,
            "title": parser.title,
            "content_type": content_type,
            "focus": focus,
            "matched_sections": _focused_passages(content, focus),
            "content": content[:_MAX_PAGE_CHARS],
            "truncated": len(content) > _MAX_PAGE_CHARS,
        }

    async def _research_search_with_diagnostics(
        self,
        *,
        query: str,
        language: str,
    ) -> tuple[list[SearchHit], list[str]]:
        gathered = await asyncio.gather(
            _ddg_search(query),
            _wiki_search(query, language),
            return_exceptions=True,
        )
        task_meta = ("duckduckgo", f"wikipedia_{language}")

        hits: list[SearchHit] = []
        errors: list[str] = []
        seen_urls: set[str] = set()
        for source_name, result in zip(task_meta, gathered):
            if isinstance(result, Exception):
                errors.append(f"{query}/{source_name}: {_error_summary(result)}")
                continue
            for hit in result:
                if hit.url in seen_urls:
                    continue
                seen_urls.add(hit.url)
                hit.query_node = query
                hits.append(hit)
                if len(hits) >= 8:
                    return hits, errors
        return hits, errors

    async def _run_research(self, arguments: dict[str, Any]) -> dict[str, Any]:
        objective = str(arguments.get("objective") or "").strip()
        if not objective:
            raise ValueError("web_research requires objective")

        language = str(arguments.get("language") or "").strip().lower()
        if not _LANGUAGE_RE.fullmatch(language):
            raise ValueError(
                "web_research requires a valid Wikipedia language/subdomain in language "
                "(for example 'ko', 'en', or 'ja')"
            )

        preferred_domains = _clean_domains(arguments.get("preferred_domains"))
        results, source_errors = await self._research_search_with_diagnostics(
            query=objective,
            language=language,
        )
        ranked_results = _rank_research_results(
            results,
            objective=objective,
            preferred_domains=preferred_domains,
        )
        focus = _objective_terms(objective)[:8]

        selected_hits: list[SearchHit] = []
        selected_urls: set[str] = set()
        for hit in ranked_results:
            if hit.url in selected_urls:
                continue
            selected_urls.add(hit.url)
            selected_hits.append(hit)
            if len(selected_hits) == 3:
                break

        page_outputs = await asyncio.gather(
            *[
                self._run_page_read({"url": hit.url, "focus": focus})
                for hit in selected_hits
            ],
            return_exceptions=True,
        )

        evidence: list[dict[str, Any]] = []
        page_errors: list[str] = []
        for hit, page_output in zip(selected_hits, page_outputs):
            if isinstance(page_output, Exception):
                page_errors.append(f"{hit.url}: {_error_summary(page_output)}")
                continue
            evidence.append(
                {
                    "url": page_output.get("url") or hit.url,
                    "title": page_output.get("title") or hit.title,
                    "query_node": hit.query_node,
                    "matched_sections": page_output.get("matched_sections") or [],
                    "excerpt": str(page_output.get("content") or "")[:2500],
                    "truncated": bool(page_output.get("truncated")),
                }
            )

        return {
            "ok": bool(ranked_results),
            "objective": objective,
            "language": language,
            "preferred_domains": preferred_domains,
            "queries": [objective],
            "status": "evidence_found" if evidence else ("snippets_only" if ranked_results else "no_results"),
            "results": [asdict(hit) for hit in ranked_results],
            "evidence": evidence,
            "source_errors": source_errors,
            "page_errors": page_errors,
        }
