from __future__ import annotations

import asyncio
import html
import urllib.parse

import httpx

_MAX_TEXT_LEN = 2500


def _ddg_sync(query: str) -> str | None:
    try:
        from duckduckgo_search import DDGS
        with DDGS(timeout=8) as ddgs:
            results = list(ddgs.text(query, max_results=5, region="kr-ko"))
        lines = []
        for item in results:
            title = item.get("title") or ""
            body = item.get("body") or ""
            href = item.get("href") or ""
            if title or body:
                lines.append(f"{title}\n{body}\n{href}")
        return "\n\n".join(lines) if lines else None
    except Exception:
        return None


async def _wiki_summary(client: httpx.AsyncClient, query: str, lang: str) -> str | None:
    base = f"https://{lang}.wikipedia.org"
    params = {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 2}
    try:
        search_response = await client.get(f"{base}/w/api.php", params=params, timeout=8)
        search_response.raise_for_status()
        titles = [item["title"] for item in search_response.json().get("query", {}).get("search", [])]
        texts = []
        for title in titles:
            url_title = urllib.parse.quote(title.replace(" ", "_"))
            summary_response = await client.get(f"{base}/api/rest_v1/page/summary/{url_title}", timeout=8)
            if summary_response.status_code == 200:
                data = summary_response.json()
                extract = html.unescape(data.get("extract") or "")
                if extract:
                    texts.append(f"Wikipedia({lang}) {title}: {extract}")
        return "\n".join(texts) if texts else None
    except Exception:
        return None


async def search(query: str) -> str | None:
    if not query.strip():
        return None
    async with httpx.AsyncClient() as client:
        parts = [part for part in await asyncio.gather(asyncio.to_thread(_ddg_sync, query), _wiki_summary(client, query, "ko"), _wiki_summary(client, query, "en")) if part]
    text = "\n\n".join(parts)
    return text[:_MAX_TEXT_LEN] if text else None
