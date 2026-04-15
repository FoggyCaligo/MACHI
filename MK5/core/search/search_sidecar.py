from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from core.entities.conclusion import CoreConclusion
from core.entities.thought_view import ThoughtView
from core.search.search_need_evaluator import SearchNeedDecision, SearchNeedEvaluator
from core.search.search_query_planner import SearchPlan, SearchQueryPlanner, SearchQueryPlannerError


@dataclass(slots=True)
class SearchEvidence:
    title: str
    snippet: str
    url: str
    provider: str = 'trusted-search'
    source_type: str = 'search'
    claim_domain: str = 'world_fact'
    trust_hint: float = 0.5
    source_provenance: str = 'trusted_search'
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text_for_graph(self) -> str:
        if self.snippet:
            return f'{self.title}: {self.snippet}'
        return self.title


@dataclass(slots=True)
class SearchRunResult:
    attempted: bool
    decision: SearchNeedDecision
    plan: SearchPlan | None = None
    results: list[SearchEvidence] = field(default_factory=list)
    error: str | None = None


class SearchBackend(Protocol):
    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> list[SearchEvidence]: ...


class SearchProvider(Protocol):
    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> list[SearchEvidence]: ...


@dataclass(slots=True)
class WikipediaSearchProvider:
    lang: str = 'ko'
    trust_hint: float = 0.88

    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> list[SearchEvidence]:
        base = (
            f'https://{self.lang}.wikipedia.org/w/api.php?action=opensearch&search={quote(query)}'
            f'&limit={max_results}&namespace=0&format=json'
        )
        request = Request(base, headers={'User-Agent': 'MK5-TrustedSearch/0.1'})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except Exception:
            return []

        titles = payload[1] if len(payload) > 1 else []
        descriptions = payload[2] if len(payload) > 2 else []
        urls = payload[3] if len(payload) > 3 else []
        evidences: list[SearchEvidence] = []
        for index, title in enumerate(titles[:max_results]):
            snippet = descriptions[index] if index < len(descriptions) else ''
            url = urls[index] if index < len(urls) else ''
            token = str(title or '').strip()
            if not token:
                continue
            evidences.append(
                SearchEvidence(
                    title=token,
                    snippet=str(snippet or '').strip(),
                    url=str(url or '').strip(),
                    provider=f'wikipedia-{self.lang}',
                    trust_hint=self.trust_hint,
                    source_provenance='trusted_search',
                    metadata={'query': query, 'lang': self.lang, 'provider_kind': 'wikipedia'},
                )
            )
        return evidences


@dataclass(slots=True)
class WikidataSearchProvider:
    lang: str = 'ko'
    trust_hint: float = 0.82

    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> list[SearchEvidence]:
        params = urlencode(
            {
                'action': 'wbsearchentities',
                'search': query,
                'language': self.lang,
                'limit': max_results,
                'format': 'json',
            }
        )
        request = Request(
            f'https://www.wikidata.org/w/api.php?{params}',
            headers={'User-Agent': 'MK5-TrustedSearch/0.1'},
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except Exception:
            return []

        entries = payload.get('search') or []
        evidences: list[SearchEvidence] = []
        for entry in entries[:max_results]:
            label = str(entry.get('label') or '').strip()
            description = str(entry.get('description') or '').strip()
            url = str(entry.get('concepturi') or '').strip()
            if not label:
                continue
            evidences.append(
                SearchEvidence(
                    title=label,
                    snippet=description,
                    url=url,
                    provider=f'wikidata-{self.lang}',
                    trust_hint=self.trust_hint,
                    source_provenance='trusted_search',
                    metadata={
                        'query': query,
                        'lang': self.lang,
                        'provider_kind': 'wikidata',
                        'entity_id': entry.get('id'),
                    },
                )
            )
        return evidences


class _DuckDuckGoHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result_link = False
        self._capture_text = False
        self._current_href = ''
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key: value or '' for key, value in attrs}
        classes = attrs_map.get('class', '')
        if tag == 'a' and 'result__a' in classes:
            self._in_result_link = True
            self._capture_text = True
            self._current_href = attrs_map.get('href', '')
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._capture_text:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == 'a' and self._in_result_link:
            title = unescape(' '.join(self._current_text)).strip()
            if title:
                self.results.append({'title': title, 'href': self._current_href})
            self._in_result_link = False
            self._capture_text = False
            self._current_href = ''
            self._current_text = []


@dataclass(slots=True)
class DuckDuckGoSearchProvider:
    trust_hint: float = 0.62

    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> list[SearchEvidence]:
        request = Request(
            f'https://html.duckduckgo.com/html/?q={quote(query)}',
            headers={'User-Agent': 'MK5-TrustedSearch/0.1'},
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                html = response.read().decode('utf-8', errors='ignore')
        except Exception:
            return []

        parser = _DuckDuckGoHtmlParser()
        try:
            parser.feed(html)
        except Exception:
            return []

        evidences: list[SearchEvidence] = []
        for item in parser.results[:max_results]:
            title = str(item.get('title') or '').strip()
            url = str(item.get('href') or '').strip()
            if not title:
                continue
            evidences.append(
                SearchEvidence(
                    title=title,
                    snippet='',
                    url=url,
                    provider='duckduckgo-web',
                    trust_hint=self.trust_hint,
                    source_provenance='trusted_search',
                    metadata={'query': query, 'provider_kind': 'duckduckgo_html'},
                )
            )
        return evidences


@dataclass(slots=True)
class TrustedSearchBackend:
    providers: list[SearchProvider] | None = None
    per_provider_max_results: int = 2

    def __post_init__(self) -> None:
        if self.providers is None:
            self.providers = [
                WikipediaSearchProvider(lang='ko', trust_hint=0.9),
                WikidataSearchProvider(lang='ko', trust_hint=0.84),
                DuckDuckGoSearchProvider(trust_hint=0.63),
                WikipediaSearchProvider(lang='en', trust_hint=0.78),
            ]

    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> list[SearchEvidence]:
        aggregated: list[SearchEvidence] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        provider_limit = max(1, min(self.per_provider_max_results, max_results))
        for provider in self.providers or []:
            items = provider.search(query, max_results=provider_limit, timeout_seconds=timeout_seconds)
            for item in items:
                title_key = item.title.strip().lower()
                url_key = item.url.strip().lower()
                if (url_key and url_key in seen_urls) or (title_key and title_key in seen_titles):
                    continue
                if url_key:
                    seen_urls.add(url_key)
                if title_key:
                    seen_titles.add(title_key)
                item.metadata = {
                    **item.metadata,
                    'query': query,
                    'source_provenance': item.source_provenance,
                    'trust_hint': item.trust_hint,
                }
                aggregated.append(item)
                if len(aggregated) >= max_results:
                    return aggregated
        return aggregated


@dataclass(slots=True)
class SearchSidecar:
    max_results: int = 6
    per_query_max_results: int = 4
    timeout_seconds: float = 4.0
    need_evaluator: SearchNeedEvaluator = field(default_factory=SearchNeedEvaluator)
    query_planner: SearchQueryPlanner = field(default_factory=SearchQueryPlanner)
    backend: SearchBackend = field(default_factory=TrustedSearchBackend)

    def should_search(self, message: str, thought_view: ThoughtView, conclusion: CoreConclusion) -> bool:
        decision = self.need_evaluator.evaluate(message=message, thought_view=thought_view, conclusion=conclusion)
        return decision.need_search

    def run(
        self,
        *,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        model_name: str,
    ) -> SearchRunResult:
        decision = self.need_evaluator.evaluate(message=message, thought_view=thought_view, conclusion=conclusion)
        if not decision.need_search:
            return SearchRunResult(attempted=False, decision=decision)

        try:
            plan = self.query_planner.plan(
                model_name=model_name,
                message=message,
                thought_view=thought_view,
                conclusion=conclusion,
                decision=decision,
            )
        except SearchQueryPlannerError as exc:
            return SearchRunResult(attempted=True, decision=decision, error=str(exc))

        results = self._execute_plan(plan)
        return SearchRunResult(attempted=True, decision=decision, plan=plan, results=results)

    def search(
        self,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        *,
        model_name: str,
    ) -> list[SearchEvidence]:
        return self.run(
            message=message,
            thought_view=thought_view,
            conclusion=conclusion,
            model_name=model_name,
        ).results

    def _execute_plan(self, plan: SearchPlan) -> list[SearchEvidence]:
        aggregated: list[SearchEvidence] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        for query in plan.queries:
            items = self.backend.search(query, max_results=self.per_query_max_results, timeout_seconds=self.timeout_seconds)
            for item in items:
                title_key = item.title.strip().lower()
                url_key = item.url.strip().lower()
                if (url_key and url_key in seen_urls) or (title_key and title_key in seen_titles):
                    continue
                if url_key:
                    seen_urls.add(url_key)
                if title_key:
                    seen_titles.add(title_key)
                item.metadata = {**item.metadata, 'planned_query': query}
                aggregated.append(item)
                if len(aggregated) >= self.max_results:
                    return aggregated
        return aggregated
