from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .. import config
from .tool_runtime import ToolDefinition, ToolRegistry


_MAX_RESULTS = 8
_WIKI_RESULTS_PER_SOURCE = 3
_HEADERS = {
    "User-Agent": "MACHI-MK5/0.2 WebSearch (+https://wikipedia.org)",
    "Accept": "application/json",
    "Accept-Language": "ko,en;q=0.8",
}
_QUERY_STOPWORDS = {
    "특징", "의의", "설명", "설명해줘", "설명해볼래", "알려줘", "한번",
    "시장", "총기시장", "비교", "차이", "대해", "대한", "무엇", "어떤", "the", "and",
    "features", "significance", "explain", "about",
}


@dataclass(slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    source: str
    query_node: str = ""


class WebSearchTool(Protocol):
    async def search(self, query: str) -> list[SearchHit]: ...


class HttpWebSearchTool:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="internet_search",
                description="Search the public internet using multiple independent sources.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "search_nodes": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            self._run,
        )
        return registry

    async def search(self, query: str) -> list[SearchHit]:
        results, _errors = await self._search_with_diagnostics(query)
        return results

    async def _search_with_diagnostics(
        self,
        query: str,
        *,
        search_nodes: list[str] | None = None,
    ) -> tuple[list[SearchHit], list[str]]:
        query = query.strip()
        if not query:
            return [], []

        query_nodes = _clean_query_nodes(search_nodes) or _query_nodes(query)
        tasks = []
        task_meta: list[tuple[str, str]] = []
        for query_node in query_nodes:
            tasks.extend([
                _ddg_search(query_node),
                _wiki_search(query_node, "ko"),
                _wiki_search(query_node, "en"),
            ])
            task_meta.extend([
                (query_node, "duckduckgo"),
                (query_node, "wikipedia_ko"),
                (query_node, "wikipedia_en"),
            ])

        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        hits: list[SearchHit] = []
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()
        per_node_counts: dict[str, int] = {}
        per_source_counts: dict[tuple[str, str], int] = {}
        for (query_node, source_name), result in zip(task_meta, gathered):
            if isinstance(result, Exception):
                errors.append(f"{query_node}/{source_name}: {_error_summary(result)}")
                continue
            for hit in result:
                source_key = (query_node, source_name)
                if per_node_counts.get(query_node, 0) >= 5:
                    break
                if per_source_counts.get(source_key, 0) >= 2:
                    break
                key = (hit.url, hit.title)
                if key in seen:
                    continue
                seen.add(key)
                hit.query_node = query_node
                hits.append(hit)
                per_node_counts[query_node] = per_node_counts.get(query_node, 0) + 1
                per_source_counts[source_key] = per_source_counts.get(source_key, 0) + 1
                if len(hits) >= _MAX_RESULTS:
                    return hits, errors
        return hits, errors

    async def _run(self, arguments: dict) -> dict:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("internet_search requires query")
        search_nodes = _argument_search_nodes(arguments.get("search_nodes"))
        query_nodes = _clean_query_nodes(search_nodes) or _query_nodes(query)
        results, errors = await self._search_with_diagnostics(query, search_nodes=query_nodes)
        return {
            "query": query,
            "search_nodes": query_nodes,
            "results": [asdict(hit) for hit in results],
            "source_errors": errors,
        }


def _argument_search_nodes(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _clean_query_nodes(raw_nodes: list[str] | None) -> list[str]:
    if not raw_nodes:
        return []
    compact: list[str] = []
    for raw in raw_nodes:
        node = raw.strip()
        if not node:
            continue
        normalized = node.lower()
        if normalized in _QUERY_STOPWORDS or len(normalized) < 2:
            continue
        if normalized not in compact:
            compact.append(normalized)
    return compact[:4]


def _query_nodes(query: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", query)
    compact: list[str] = []
    for token in tokens:
        normalized = token.lower()
        for suffix in ("에서의", "으로의", "에의", "에서", "으로", "의", "과", "와", "을", "를", "은", "는", "이", "가"):
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                normalized = normalized[:-len(suffix)]
                break
        if normalized in _QUERY_STOPWORDS or len(normalized) < 2:
            continue
        if normalized not in compact:
            compact.append(normalized)
    # Each item is an independently searchable concept node. Keeping nodes atomic
    # prevents a conversational sentence from becoming one over-constrained query.
    return compact[:4] or [query.strip()]


def _ddg_search_sync(query: str) -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS(timeout=config.WEB_SEARCH_TIMEOUT_SECONDS) as ddgs:
        return list(ddgs.text(query, max_results=5, region="kr-ko", safesearch="moderate"))


async def _ddg_search(query: str) -> list[SearchHit]:
    raw = await asyncio.wait_for(
        asyncio.to_thread(_ddg_search_sync, query),
        timeout=config.WEB_SEARCH_TIMEOUT_SECONDS,
    )
    hits: list[SearchHit] = []
    for item in raw:
        title = str(item.get("title") or "").strip()
        url = str(item.get("href") or item.get("url") or "").strip()
        snippet = str(item.get("body") or "").strip()
        if title and url and snippet:
            hits.append(SearchHit(title=title, url=url, snippet=snippet, source="duckduckgo"))
    return hits


async def _wiki_search(query: str, lang: str) -> list[SearchHit]:
    async with httpx.AsyncClient(
        timeout=config.WEB_SEARCH_TIMEOUT_SECONDS,
        headers=_HEADERS,
        follow_redirects=True,
    ) as client:
        response = await client.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "query", "list": "search", "srsearch": query,
                "format": "json", "utf8": 1, "srlimit": _WIKI_RESULTS_PER_SOURCE,
            },
        )
        response.raise_for_status()
        payload = response.json()

    hits: list[SearchHit] = []
    for item in payload.get("query", {}).get("search", []):
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        snippet = re.sub(r"<[^>]+>", "", str(item.get("snippet") or "")).strip()
        hits.append(SearchHit(
            title=title,
            url=f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
            snippet=snippet,
            source=f"wikipedia_{lang}",
        ))
    return hits


def _error_summary(error: Exception) -> str:
    message = str(error).strip()
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


class StubWebSearchTool:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="internet_search",
                description="Search the public internet for external information.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            self._run,
        )
        return registry

    async def search(self, query: str) -> list[SearchHit]:
        return [SearchHit(
            title="stub-result", url="https://example.com",
            snippet=f"stub search result for query={query}", source="stub",
        )]

    async def _run(self, arguments: dict) -> dict:
        query = str(arguments.get("query") or "").strip()
        return {"results": [asdict(hit) for hit in await self.search(query)]}
