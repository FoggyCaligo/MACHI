from __future__ import annotations

import asyncio
import re
from dataclasses import asdict
from typing import Any

from .tool_runtime import ToolDefinition, ToolRegistry
from .web_search import (
    HttpWebSearchTool,
    SearchHit,
    _clean_domains,
    _ddg_search,
    _error_summary,
    _objective_terms,
    _rank_research_results,
    _wiki_search,
)


_LANGUAGE_RE = re.compile(r"^[a-z][a-z0-9-]{1,11}$")


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
