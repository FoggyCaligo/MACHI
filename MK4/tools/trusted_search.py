from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse, quote

import requests
from bs4 import BeautifulSoup

from config import settings

TRUSTED_DOC_DOMAINS = {
    "ai.google.dev": 1.0,
    "developers.googleblog.com": 0.9,
    "docs.ollama.com": 1.0,
    "ollama.com": 0.9,
    "huggingface.co": 0.85,
    "pytorch.org": 0.9,
    "python.org": 0.9,
    "fastapi.tiangolo.com": 0.9,
    "docs.python.org": 1.0,
    "platform.openai.com": 0.9,
}

PAPER_DOMAINS = {
    "arxiv.org": 0.95,
    "doi.org": 0.95,
    "aclanthology.org": 0.95,
    "proceedings.mlr.press": 0.95,
    "openreview.net": 0.9,
    "nature.com": 0.85,
    "science.org": 0.85,
}

REPO_DOMAINS = {
    "github.com": 0.6,
}

ALL_TRUSTED = {**TRUSTED_DOC_DOMAINS, **PAPER_DOMAINS, **REPO_DOMAINS}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    domain: str
    source_type: str
    trust_score: float
    fetched_excerpt: str = ""


class SearchError(RuntimeError):
    pass


def normalize_domain(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def classify_domain(domain: str) -> tuple[str, float]:
    if domain in TRUSTED_DOC_DOMAINS:
        return "official_doc", TRUSTED_DOC_DOMAINS[domain]
    if domain in PAPER_DOMAINS:
        return "paper", PAPER_DOMAINS[domain]
    if domain in REPO_DOMAINS:
        return "repository", REPO_DOMAINS[domain]
    return "untrusted", 0.0


def fetch_readable_text(url: str, timeout: int = 20) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GemmaTrustedSearch/1.0)"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:5000]


def search_arxiv(query: str, max_results: int = 3) -> list[SearchResult]:
    api_url = (
        "http://export.arxiv.org/api/query?search_query="
        + quote(f"all:{query}")
        + f"&start=0&max_results={max_results}"
    )
    resp = requests.get(api_url, timeout=20)
    resp.raise_for_status()
    xml = resp.text

    entries = re.findall(r"<entry>(.*?)</entry>", xml, flags=re.DOTALL)
    results: list[SearchResult] = []
    for entry in entries:
        title_match = re.search(r"<title>(.*?)</title>", entry, flags=re.DOTALL)
        summary_match = re.search(r"<summary>(.*?)</summary>", entry, flags=re.DOTALL)
        id_match = re.search(r"<id>(.*?)</id>", entry)
        if not (title_match and summary_match and id_match):
            continue
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        summary = re.sub(r"\s+", " ", summary_match.group(1)).strip()
        url = id_match.group(1).strip()
        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=summary[:500],
                domain="arxiv.org",
                source_type="paper",
                trust_score=0.95,
            )
        )
    return results


def ollama_web_search(query: str, max_results: int | None = None) -> list[dict[str, Any]]:
    if not settings.internet_search_enabled:
        raise SearchError("INTERNET_SEARCH_ENABLED=false 입니다.")
    if not settings.ollama_api_key:
        raise SearchError("OLLAMA_API_KEY가 비어 있습니다.")

    max_results = max_results or settings.max_search_results
    payload = {"query": query, "max_results": max_results}
    headers = {
        "Authorization": f"Bearer {settings.ollama_api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        settings.ollama_web_search_url,
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", [])


def filter_and_fetch(raw_results: list[dict[str, Any]], fetch_pages: bool = True) -> list[SearchResult]:
    filtered: list[SearchResult] = []
    seen: set[str] = set()

    for item in raw_results:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        domain = normalize_domain(url)
        source_type, trust = classify_domain(domain)
        if source_type == "untrusted":
            continue

        result = SearchResult(
            title=item.get("title", "(untitled)"),
            url=url,
            snippet=item.get("content", "")[:600],
            domain=domain,
            source_type=source_type,
            trust_score=trust,
        )
        if fetch_pages:
            try:
                result.fetched_excerpt = fetch_readable_text(url)[:1500]
            except Exception:
                result.fetched_excerpt = ""
        filtered.append(result)

    filtered.sort(key=lambda x: (x.trust_score, x.source_type == "official_doc"), reverse=True)
    return filtered


def trusted_search(query: str, max_results: int = 8) -> dict[str, Any]:
    """
    Search trusted sources only.

    Prioritizes official documentation and papers. Untrusted domains are dropped.
    """
    web_queries = [
        query,
        f"{query} official documentation",
        f"{query} arXiv paper",
    ]

    raw_results: list[dict[str, Any]] = []
    for q in web_queries:
        try:
            raw_results.extend(ollama_web_search(q, max_results=max_results))
        except Exception:
            continue

    trusted = filter_and_fetch(raw_results, fetch_pages=True)

    try:
        arxiv_results = search_arxiv(query, max_results=3)
    except Exception:
        arxiv_results = []

    merged: list[SearchResult] = []
    seen_urls: set[str] = set()
    for item in trusted + arxiv_results:
        if item.url in seen_urls:
            continue
        seen_urls.add(item.url)
        merged.append(item)

    merged.sort(key=lambda x: (x.trust_score, x.source_type == "official_doc"), reverse=True)
    merged = merged[:max_results]

    return {
        "query": query,
        "policy": "official documentation and papers only",
        "results": [asdict(item) for item in merged],
    }
