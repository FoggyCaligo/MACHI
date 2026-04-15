from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
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
    provider: str = 'wikipedia'
    source_type: str = 'search'
    claim_domain: str = 'world_fact'
    trust_hint: str = 'medium'
    source_provenance: str = 'trusted_search'
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text_for_graph(self) -> str:
        if self.snippet:
            return f'{self.title}: {self.snippet}'
        return self.title


@dataclass(slots=True)
class SearchProviderError:
    provider: str
    query: str
    error: str


@dataclass(slots=True)
class SearchBackendResult:
    results: list[SearchEvidence] = field(default_factory=list)
    provider_errors: list[SearchProviderError] = field(default_factory=list)


@dataclass(slots=True)
class SearchRunResult:
    attempted: bool
    decision: SearchNeedDecision
    plan: SearchPlan | None = None
    results: list[SearchEvidence] = field(default_factory=list)
    provider_errors: list[SearchProviderError] = field(default_factory=list)
    error: str | None = None


class SearchBackend(Protocol):
    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> SearchBackendResult: ...


@dataclass(slots=True)
class WikipediaSearchBackend:
    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> SearchBackendResult:
        aggregated = SearchBackendResult()
        for lang in ('ko', 'en'):
            result = self._search_wikipedia(query, lang=lang, max_results=max_results, timeout_seconds=timeout_seconds)
            aggregated.provider_errors.extend(result.provider_errors)
            for item in result.results:
                aggregated.results.append(item)
                if len(aggregated.results) >= max_results:
                    return aggregated
        return aggregated

    def _search_wikipedia(self, query: str, *, lang: str, max_results: int, timeout_seconds: float) -> SearchBackendResult:
        provider = f'wikipedia-{lang}'
        base = f'https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={quote(query)}&limit={max_results}&namespace=0&format=json'
        request = Request(base, headers={'User-Agent': 'MK5-SearchSidecar/0.1'})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except HTTPError as exc:
            return SearchBackendResult(provider_errors=[SearchProviderError(provider=provider, query=query, error=f'HTTP {exc.code}')])
        except (URLError, TimeoutError, OSError) as exc:
            return SearchBackendResult(provider_errors=[SearchProviderError(provider=provider, query=query, error=str(exc))])
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return SearchBackendResult(provider_errors=[SearchProviderError(provider=provider, query=query, error=f'invalid_json:{exc}')])
        except Exception as exc:  # pragma: no cover - defensive catch to surface failures, not hide them
            return SearchBackendResult(provider_errors=[SearchProviderError(provider=provider, query=query, error=f'unexpected:{exc}')])

        titles = payload[1] if len(payload) > 1 else []
        descriptions = payload[2] if len(payload) > 2 else []
        urls = payload[3] if len(payload) > 3 else []
        evidences: list[SearchEvidence] = []
        for index, title in enumerate(titles[:max_results]):
            snippet = descriptions[index] if index < len(descriptions) else ''
            url = urls[index] if index < len(urls) else ''
            if not title:
                continue
            evidences.append(
                SearchEvidence(
                    title=str(title),
                    snippet=str(snippet or ''),
                    url=str(url or ''),
                    provider=provider,
                    trust_hint='medium',
                    source_provenance='trusted_search:wikipedia',
                    metadata={'query': query, 'lang': lang},
                )
            )
        return SearchBackendResult(results=evidences)


@dataclass(slots=True)
class SearchSidecar:
    max_results: int = 3
    timeout_seconds: float = 4.0
    need_evaluator: SearchNeedEvaluator = field(default_factory=SearchNeedEvaluator)
    query_planner: SearchQueryPlanner = field(default_factory=SearchQueryPlanner)
    backend: SearchBackend = field(default_factory=WikipediaSearchBackend)

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

        results, provider_errors = self._execute_plan(plan)
        error = None
        if not results and provider_errors:
            error = 'search_transport_failure'
        return SearchRunResult(
            attempted=True,
            decision=decision,
            plan=plan,
            results=results,
            provider_errors=provider_errors,
            error=error,
        )

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

    def _execute_plan(self, plan: SearchPlan) -> tuple[list[SearchEvidence], list[SearchProviderError]]:
        aggregated: list[SearchEvidence] = []
        provider_errors: list[SearchProviderError] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        for query in plan.queries:
            backend_result = self.backend.search(query, max_results=self.max_results, timeout_seconds=self.timeout_seconds)
            provider_errors.extend(backend_result.provider_errors)
            for item in backend_result.results:
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
                    return aggregated, provider_errors
        return aggregated, provider_errors
