"""External search used by ThoughtEngine."""
from __future__ import annotations

import asyncio
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
_HTTP_HEADERS = {
    "User-Agent": "MK6_1/0.1 (local-dev)",
    "Accept": "application/json",
    "Accept-Language": "ko,en;q=0.8",
}


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


async def _ddg_search(query: str) -> list[str]:
    results: list[dict[str, Any]] = await asyncio.wait_for(
        asyncio.to_thread(_ddg_search_sync, query),
        timeout=_DDG_GATHER_TIMEOUT,
    )

    seen: set[str] = set()
    parts: list[str] = []
    for result in results:
        body = (result.get("body") or "").strip()
        if not body or body in seen:
            continue
        seen.add(body)
        title = (result.get("title") or "").strip()
        parts.append(f"{title}. {body}" if title else body)
    return parts


async def _wiki_search(query: str, lang: str) -> list[str]:
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

        async def fetch_summary(title: str) -> str:
            response = await client.get(
                _WIKI_SUMMARY_URL.format(lang=lang, title=title.replace(" ", "_"))
            )
            response.raise_for_status()
            data = response.json()
            extract = (data.get("extract") or "").strip()
            page_title = (data.get("title") or "").strip()
            if not extract:
                return ""
            return f"{page_title}. {extract}" if page_title else extract

        summaries = await asyncio.gather(
            *[fetch_summary(hit["title"]) for hit in hits],
            return_exceptions=True,
        )
        return [summary for summary in summaries if isinstance(summary, str) and summary]


def _combine(parts: list[str]) -> str | None:
    if not parts:
        return None
    text = " ".join(parts)
    if len(text) > _MAX_TEXT_LEN:
        text = text[:_MAX_TEXT_LEN].rsplit(" ", 1)[0]
    return text.strip() or None


async def search(query: str) -> str | None:
    results = await asyncio.gather(
        _ddg_search(query),
        _wiki_search(query, "ko"),
        _wiki_search(query, "en"),
        return_exceptions=True,
    )
    source_names = ["ddg", "wiki_ko", "wiki_en"]

    parts: list[str] = []
    errors: list[tuple[str, Exception]] = []
    for source_name, result in zip(source_names, results):
        if isinstance(result, Exception):
            errors.append((source_name, result))
            continue
        parts.extend(result)

    if errors:
        details = "; ".join(f"{name}:{type(err).__name__}" for name, err in errors)
        print(f"[search] partial_source_failure query={query!r} details={details}")

    combined = _combine(parts)
    if combined is not None:
        return combined

    if errors:
        detail_text = "; ".join(f"{name}:{err}" for name, err in errors)
        raise RuntimeError(f"search failed for query={query!r}: {detail_text}") from errors[0][1]

    return None
