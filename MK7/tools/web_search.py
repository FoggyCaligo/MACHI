from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

import httpx

from .. import config
from .tool_runtime import ToolDefinition, ToolRegistry


@dataclass(slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    source: str


class WebSearchTool(Protocol):
    async def search(self, query: str) -> list[SearchHit]: ...


class HttpWebSearchTool:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="internet_search",
                description="Search the public internet for external information.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            self._run,
        )
        return registry

    async def search(self, query: str) -> list[SearchHit]:
        query = query.strip()
        if not query:
            return []

        results: list[SearchHit] = []
        async with httpx.AsyncClient(timeout=config.WEB_SEARCH_TIMEOUT_SECONDS) as client:
            wiki_ko = await client.get(
                "https://ko.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "utf8": 1,
                    "srlimit": 3,
                },
                headers={"User-Agent": "MK7/0.1 WebSearch"},
            )
            wiki_ko.raise_for_status()
            payload = wiki_ko.json()

        for item in payload.get("query", {}).get("search", []):
            title = item.get("title")
            if not isinstance(title, str):
                continue
            snippet = str(item.get("snippet") or "")
            results.append(
                SearchHit(
                    title=title,
                    url=f"https://ko.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    snippet=snippet,
                    source="wikipedia_ko",
                )
            )
        return results

    async def _run(self, arguments: dict) -> dict:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("internet_search requires query")
        return {"results": [asdict(hit) for hit in await self.search(query)]}


class StubWebSearchTool:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="internet_search",
                description="Search the public internet for external information.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            ),
            self._run,
        )
        return registry

    async def search(self, query: str) -> list[SearchHit]:
        return [
            SearchHit(
                title="stub-result",
                url="https://example.com",
                snippet=f"stub search result for query={query}",
                source="stub",
            )
        ]

    async def _run(self, arguments: dict) -> dict:
        query = str(arguments.get("query") or "").strip()
        return {"results": [asdict(hit) for hit in await self.search(query)]}
