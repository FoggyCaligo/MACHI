"""External search used by ThoughtEngine."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


_DDG_MAX_RESULTS = 5
_DDG_TIMEOUT = 8.0
_DDG_GATHER_TIMEOUT = 12.0
_WIKI_MAX_RESULTS = 3
_WIKI_TIMEOUT = 8.0
_MAX_TEXT_LEN = 2500
_WIKI_SEARCH_URL = "https://{lang}.wikipedia.org/w/api.php"
_WIKI_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"
_WIKI_PAGE_URL = "https://{lang}.wikipedia.org/wiki/{title}"
_HTTP_HEADERS = {
    "User-Agent": "MK4/0.1 SearchClient (Windows; local development; +https://wikipedia.org)",
    "Accept": "application/json",
    "Accept-Language": "ko,en;q=0.8",
}


@dataclass(frozen=True, slots=True)
class SearchResult:
    query: str
    source: str
    title: str | None
    url: str | None
    snippet: str
    rank: int


@dataclass(frozen=True, slots=True)
class SearchBundle:
    query: str
    results: list[SearchResult]


def _ddg_search_sync(query: str) -> list[dict[str, Any]]:
    from ddgs import DDGS

    with DDGS(timeout=_DDG_TIMEOUT) as ddgs:
        kr = list(ddgs.text(
            query,
            max_results=_DDG_MAX_RESULTS,
            region="kr-ko",
            safesearch="moderate",
        ))
        us = list(ddgs.text(
            query,
            max_results=_DDG_MAX_RESULTS,
            region="us-en",
            safesearch="moderate",
        ))
    return kr + us


async def _ddg_search(query: str) -> list[SearchResult]:
    raw_results: list[dict[str, Any]] = await asyncio.wait_for(
        asyncio.to_thread(_ddg_search_sync, query),
        timeout=_DDG_GATHER_TIMEOUT,
    )

    seen: set[tuple[str, str, str]] = set()
    results: list[SearchResult] = []
    for result in raw_results:
        snippet = (result.get("body") or "").strip()
        if not snippet:
            continue
        title = (result.get("title") or "").strip() or None
        url = (result.get("href") or result.get("url") or "").strip() or None
        key = (title or "", url or "", snippet)
        if key in seen:
            continue
        seen.add(key)
        results.append(SearchResult(
            query=query,
            source="ddg",
            title=title,
            url=url,
            snippet=snippet,
            rank=len(results) + 1,
        ))
    return results


async def _wiki_search(query: str, lang: str) -> list[SearchResult]:
    async with httpx.AsyncClient(
        timeout=_WIKI_TIMEOUT,
        headers=_HTTP_HEADERS,
        follow_redirects=True,
    ) as client:
        search_response = await client.get(
            _WIKI_SEARCH_URL.format(lang=lang),
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "utf8": 1,
                "srlimit": _WIKI_MAX_RESULTS,
            },
        )
        search_response.raise_for_status()
        hits = search_response.json().get("query", {}).get("search", [])

        async def fetch_summary(title: str) -> SearchResult | None:
            response = await client.get(
                _WIKI_SUMMARY_URL.format(lang=lang, title=title.replace(" ", "_"))
            )
            response.raise_for_status()
            data = response.json()
            snippet = (data.get("extract") or "").strip()
            page_title = (data.get("title") or "").strip() or title
            if not snippet:
                return None
            page_url = _WIKI_PAGE_URL.format(lang=lang, title=page_title.replace(" ", "_"))
            return SearchResult(
                query=query,
                source=f"wiki_{lang}",
                title=page_title,
                url=page_url,
                snippet=snippet,
                rank=0,
            )

        summaries = await asyncio.gather(
            *[fetch_summary(hit["title"]) for hit in hits],
            return_exceptions=True,
        )
        results: list[SearchResult] = []
        for summary in summaries:
            if isinstance(summary, Exception):
                continue
            if summary is None:
                continue
            results.append(SearchResult(
                query=summary.query,
                source=summary.source,
                title=summary.title,
                url=summary.url,
                snippet=summary.snippet,
                rank=len(results) + 1,
            ))
        return results


def _combine(results: list[SearchResult]) -> str | None:
    if not results:
        return None
    parts: list[str] = []
    for item in results:
        if item.title:
            parts.append(f"{item.title}. {item.snippet}")
        else:
            parts.append(item.snippet)
    text = " ".join(parts)
    if len(text) > _MAX_TEXT_LEN:
        text = text[:_MAX_TEXT_LEN].rsplit(" ", 1)[0]
    return text.strip() or None


async def search_structured(query: str) -> SearchBundle:
    gathered = await asyncio.gather(
        _ddg_search(query),
        _wiki_search(query, "ko"),
        _wiki_search(query, "en"),
        return_exceptions=True,
    )
    source_names = ["ddg", "wiki_ko", "wiki_en"]

    combined_results: list[SearchResult] = []
    errors: list[tuple[str, Exception]] = []

    for source_name, result in zip(source_names, gathered):
        if isinstance(result, Exception):
            errors.append((source_name, result))
            continue
        for item in result:
            combined_results.append(SearchResult(
                query=item.query,
                source=item.source,
                title=item.title,
                url=item.url,
                snippet=item.snippet,
                rank=len(combined_results) + 1,
            ))

    if errors:
        details = "; ".join(f"{name}:{_error_summary(err)}" for name, err in errors)
        print(f"[search] partial_source_failure query={query!r} details={details}")

    if not combined_results and errors:
        detail_text = "; ".join(f"{name}:{_error_summary(err)}" for name, err in errors)
        print(f"[search] all_sources_failed query={query!r} details={detail_text}")
        return SearchBundle(query=query, results=[])

    return SearchBundle(query=query, results=combined_results)


async def search(query: str) -> str | None:
    bundle = await search_structured(query)
    return _combine(bundle.results)


def _error_summary(err: Exception) -> str:
    message = str(err).strip()
    if not message:
        return type(err).__name__
    return f"{type(err).__name__}: {message}"

