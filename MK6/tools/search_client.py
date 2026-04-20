"""웹 검색 클라이언트 — DuckDuckGo + Wikipedia.

search() 함수는 ThoughtEngine의 search_fn 시그니처와 일치한다:
  async (query: str) -> str | None

검색 순서:
  1. DuckDuckGo 텍스트 검색
  2. Wikipedia 한국어
  3. Wikipedia 영어
결과를 합산해 하나의 텍스트로 반환한다.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx


# ── 설정 ──────────────────────────────────────────────────────────────────────

_DDG_MAX_RESULTS  = 5
_DDG_TIMEOUT      = 8.0  # DDGS HTTP 소켓 타임아웃 (초)
_DDG_GATHER_TIMEOUT = 12.0  # 두 지역 DDG 병렬 gather 전체 상한 (초)
_WIKI_MAX_RESULTS = 3    # 언어별 최대 문서 수
_WIKI_TIMEOUT     = 8.0  # Wikipedia API 타임아웃 (초)
_MAX_TEXT_LEN     = 2500 # 최종 텍스트 최대 길이


# ── DuckDuckGo ────────────────────────────────────────────────────────────────

def _ddg_search_sync(query: str, region: str) -> list[dict[str, Any]]:
    """동기 DuckDuckGo 검색. asyncio.to_thread 안에서 실행된다.

    DDGS(timeout=...) 로 소켓 수준 타임아웃을 설정한다.
    asyncio 레벨 취소는 스레드를 멈추지 못하므로 여기서 직접 제한한다.
    """
    from ddgs import DDGS
    with DDGS(timeout=_DDG_TIMEOUT) as ddgs:
        return list(ddgs.text(
            query,
            max_results=_DDG_MAX_RESULTS,
            region=region,
            safesearch="moderate",
        ))


async def _ddg_search(query: str) -> list[str]:
    """DuckDuckGo 결과를 한국(kr-ko) + 미국(us-en) 두 지역에서 검색해 반환한다.

    _DDG_GATHER_TIMEOUT 초 안에 완료되지 않으면 빈 리스트를 반환한다.
    """
    try:
        kr_results, us_results = await asyncio.wait_for(
            asyncio.gather(
                asyncio.to_thread(_ddg_search_sync, query, "kr-ko"),
                asyncio.to_thread(_ddg_search_sync, query, "us-en"),
            ),
            timeout=_DDG_GATHER_TIMEOUT,
        )
    except Exception:
        return []

    # 중복 제거: body 기준으로 이미 추가된 텍스트는 건너뜀
    seen: set[str] = set()
    parts: list[str] = []
    for r in list(kr_results) + list(us_results):
        body = (r.get("body") or "").strip()
        if not body or body in seen:
            continue
        seen.add(body)
        title = (r.get("title") or "").strip()
        parts.append(f"{title}. {body}" if title else body)
    return parts


# ── Wikipedia ─────────────────────────────────────────────────────────────────

_WIKI_SEARCH_URL  = "https://{lang}.wikipedia.org/w/api.php"
_WIKI_SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"


async def _wiki_search(query: str, lang: str) -> list[str]:
    """Wikipedia에서 query를 검색하고 요약 텍스트 조각 리스트를 반환한다.

    Args:
        query: 검색어
        lang:  언어 코드 ("ko" | "en")
    """
    parts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=_WIKI_TIMEOUT) as client:
            # 1단계: 제목 검색
            search_resp = await client.get(
                _WIKI_SEARCH_URL.format(lang=lang),
                params={
                    "action":   "query",
                    "list":     "search",
                    "srsearch": query,
                    "format":   "json",
                    "utf8":     1,
                    "srlimit":  _WIKI_MAX_RESULTS,
                },
            )
            search_resp.raise_for_status()
            hits = search_resp.json().get("query", {}).get("search", [])

            # 2단계: 각 문서의 요약 fetch (병렬)
            async def fetch_summary(title: str) -> str:
                url = _WIKI_SUMMARY_URL.format(lang=lang, title=title.replace(" ", "_"))
                try:
                    r = await client.get(url)
                    r.raise_for_status()
                    data = r.json()
                    extract = (data.get("extract") or "").strip()
                    page_title = (data.get("title") or "").strip()
                    if extract:
                        return f"{page_title}. {extract}" if page_title else extract
                except Exception:
                    pass
                return ""

            summaries = await asyncio.gather(
                *[fetch_summary(hit["title"]) for hit in hits]
            )
            parts = [s for s in summaries if s]

    except Exception:
        pass

    return parts


# ── 결합 ──────────────────────────────────────────────────────────────────────

def _combine(parts: list[str]) -> str | None:
    """텍스트 조각들을 하나로 합산하고 길이를 제한한다."""
    if not parts:
        return None
    text = " ".join(parts)
    if len(text) > _MAX_TEXT_LEN:
        text = text[:_MAX_TEXT_LEN].rsplit(" ", 1)[0]
    return text.strip() or None


# ── 공개 API ──────────────────────────────────────────────────────────────────

async def search(query: str) -> str | None:
    """DuckDuckGo + Wikipedia(ko + en)를 검색하고 결과 텍스트를 반환한다.

    ThoughtEngine의 search_fn으로 직접 사용 가능하다.

    검색 소스별 결과를 모아 하나의 텍스트로 합산한다.
    모든 소스에서 결과가 없으면 None을 반환한다.

    Returns:
        결과 텍스트 (str) — LangToGraph에 전달될 자연어 문자열
        결과 없음 또는 오류 시 None
    """
    ddg_task  = _ddg_search(query)
    wiki_ko   = _wiki_search(query, lang="ko")
    wiki_en   = _wiki_search(query, lang="en")

    ddg_parts, ko_parts, en_parts = await asyncio.gather(ddg_task, wiki_ko, wiki_en)

    # DuckDuckGo → 한국어 Wiki → 영어 Wiki 순으로 합산
    all_parts = ddg_parts + ko_parts + en_parts
    return _combine(all_parts)
