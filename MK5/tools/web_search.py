from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlencode

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
        registry.register(
            ToolDefinition(
                name="latest_search",
                description=(
                    "Search recent public news/web documents for time-sensitive questions. "
                    "Use this for current events, market situations, policy announcements, "
                    "incidents, releases, and other freshness-sensitive topics. This is not "
                    "a real-time quote API; it returns recent source snippets with freshness metadata."
                ),
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
            self._run_latest,
        )
        registry.register(
            ToolDefinition(
                name="market_snapshot",
                description=(
                    "Fetch a delayed numeric market snapshot for Korean market indicators. "
                    "Use with latest_search for current Korean stock market situation questions. "
                    "Returns KOSPI, KOSDAQ, and USD/KRW when available. Not guaranteed real-time."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "market": {"type": "string"},
                    },
                    "required": ["market"],
                    "additionalProperties": False,
                },
            ),
            self._run_market_snapshot,
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

        query_nodes = _clean_query_nodes(search_nodes) or [query]
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
        query_nodes = _clean_query_nodes(search_nodes) or [query]
        results, errors = await self._search_with_diagnostics(query, search_nodes=query_nodes)
        return {
            "query": query,
            "search_nodes": query_nodes,
            "results": [asdict(hit) for hit in results],
            "source_errors": errors,
        }

    async def _run_latest(self, arguments: dict) -> dict:
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("latest_search requires query")
        search_nodes = _argument_search_nodes(arguments.get("search_nodes"))
        query_nodes = _clean_query_nodes(search_nodes) or [query]
        results, errors = await self._latest_with_diagnostics(query_nodes=query_nodes)
        return {
            "ok": bool(results),
            "query": query,
            "search_nodes": query_nodes,
            "freshness": "recent_news" if results else "unknown",
            "results": [asdict(hit) for hit in results],
            "source_errors": errors,
        }

    async def _latest_with_diagnostics(self, *, query_nodes: list[str]) -> tuple[list[SearchHit], list[str]]:
        tasks = []
        task_meta: list[tuple[str, str]] = []
        for query_node in query_nodes:
            tasks.extend([
                _ddg_news_search(query_node),
                _google_news_rss_search(query_node),
            ])
            task_meta.extend([
                (query_node, "duckduckgo_news"),
                (query_node, "google_news_rss"),
            ])
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        hits: list[SearchHit] = []
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()
        per_node_counts: dict[str, int] = {}
        for (query_node, source_name), result in zip(task_meta, gathered):
            if isinstance(result, Exception):
                errors.append(f"{query_node}/{source_name}: {_error_summary(result)}")
                continue
            for hit in result:
                if per_node_counts.get(query_node, 0) >= 5:
                    break
                key = (hit.url, hit.title)
                if key in seen:
                    continue
                seen.add(key)
                hit.query_node = query_node
                hits.append(hit)
                per_node_counts[query_node] = per_node_counts.get(query_node, 0) + 1
                if len(hits) >= _MAX_RESULTS:
                    return hits, errors
        return hits, errors

    async def _run_market_snapshot(self, arguments: dict) -> dict:
        market = str(arguments.get("market") or "").strip().upper()
        if market not in {"KR", "KOREA", "한국", "한국장"}:
            return {
                "ok": False,
                "market": market or None,
                "freshness": "unknown",
                "source": "yahoo_finance_chart",
                "indicators": [],
                "source_errors": [f"Unsupported market: {market or '<empty>'}"],
            }

        specs = [
            ("KOSPI", "^KS11"),
            ("KOSDAQ", "^KQ11"),
            ("USD/KRW", "KRW=X"),
        ]
        gathered = await asyncio.gather(
            *[_yahoo_chart_snapshot(symbol) for _name, symbol in specs],
            return_exceptions=True,
        )
        indicators: list[dict[str, Any]] = []
        errors: list[str] = []
        for (name, symbol), result in zip(specs, gathered):
            if isinstance(result, Exception):
                errors.append(f"{name}/{symbol}: {_error_summary(result)}")
                continue
            if result is None:
                errors.append(f"{name}/{symbol}: no quote data")
                continue
            indicators.append({"name": name, "symbol": symbol, **result})
        return {
            "ok": bool(indicators),
            "market": "KR",
            "freshness": "delayed_quote" if indicators else "unknown",
            "source": "yahoo_finance_chart",
            "disclaimer": "Market data may be delayed and is not guaranteed real-time.",
            "indicators": indicators,
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
        if len(node) < 2:
            continue
        if node not in compact:
            compact.append(node)
    return compact[:4]


def _ddg_search_sync(query: str) -> list[dict[str, Any]]:
    try:
        from ddgs import DDGS
    except ModuleNotFoundError:
        return []

    with DDGS(timeout=config.WEB_SEARCH_TIMEOUT_SECONDS) as ddgs:
        return list(ddgs.text(query, max_results=5, region="kr-ko", safesearch="moderate"))


def _ddg_news_search_sync(query: str) -> list[dict[str, Any]]:
    try:
        from ddgs import DDGS
    except ModuleNotFoundError:
        return []

    with DDGS(timeout=config.WEB_SEARCH_TIMEOUT_SECONDS) as ddgs:
        return list(ddgs.news(query, max_results=5, region="kr-ko", safesearch="moderate"))


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


async def _ddg_news_search(query: str) -> list[SearchHit]:
    raw = await asyncio.wait_for(
        asyncio.to_thread(_ddg_news_search_sync, query),
        timeout=config.WEB_SEARCH_TIMEOUT_SECONDS,
    )
    hits: list[SearchHit] = []
    for item in raw:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or item.get("href") or "").strip()
        snippet = str(item.get("body") or item.get("excerpt") or "").strip()
        date = str(item.get("date") or "").strip()
        source = str(item.get("source") or "").strip()
        if date:
            snippet = f"{date} — {snippet}" if snippet else date
        if source:
            snippet = f"{source}: {snippet}" if snippet else source
        if title and url and snippet:
            hits.append(SearchHit(title=title, url=url, snippet=snippet, source="duckduckgo_news"))
    return hits


async def _google_news_rss_search(query: str) -> list[SearchHit]:
    params = urlencode({
        "q": query,
        "hl": "ko",
        "gl": "KR",
        "ceid": "KR:ko",
    })
    async with httpx.AsyncClient(
        timeout=config.WEB_SEARCH_TIMEOUT_SECONDS,
        headers={**_HEADERS, "Accept": "application/rss+xml, application/xml, text/xml"},
        follow_redirects=True,
    ) as client:
        response = await client.get(f"https://news.google.com/rss/search?{params}")
        response.raise_for_status()
        text = response.text

    root = ET.fromstring(text)
    hits: list[SearchHit] = []
    for item in root.findall("./channel/item")[:5]:
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        description = re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip()
        snippet = " — ".join(part for part in [pub_date, description] if part)
        if title and url and snippet:
            hits.append(SearchHit(title=title, url=url, snippet=snippet, source="google_news_rss"))
    return hits


async def _yahoo_chart_snapshot(symbol: str) -> dict[str, Any] | None:
    url_symbol = quote(symbol, safe="")
    async with httpx.AsyncClient(
        timeout=config.WEB_SEARCH_TIMEOUT_SECONDS,
        headers={**_HEADERS, "Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        response = await client.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{url_symbol}",
            params={"range": "1d", "interval": "1m"},
        )
        response.raise_for_status()
        payload = response.json()

    chart = payload.get("chart") if isinstance(payload, dict) else None
    results = chart.get("result") if isinstance(chart, dict) else None
    if not isinstance(results, list) or not results:
        return None
    item = results[0]
    if not isinstance(item, dict):
        return None
    meta = item.get("meta")
    if not isinstance(meta, dict):
        return None
    price = _float_or_none(meta.get("regularMarketPrice"))
    previous_close = _float_or_none(meta.get("chartPreviousClose") or meta.get("previousClose"))
    if price is None:
        return None
    change = price - previous_close if previous_close is not None else None
    change_percent = (change / previous_close * 100) if change is not None and previous_close else None
    return {
        "price": price,
        "previous_close": previous_close,
        "change": change,
        "change_percent": change_percent,
        "currency": meta.get("currency"),
        "exchange_name": meta.get("exchangeName"),
        "market_state": meta.get("marketState"),
        "regular_market_time": meta.get("regularMarketTime"),
        "timezone": meta.get("exchangeTimezoneName"),
    }


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
