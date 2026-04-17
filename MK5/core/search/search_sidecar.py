from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

from config import SEARCH_BACKEND_TIMEOUT_SECONDS, SEARCH_MAX_RESULTS
from core.entities.conclusion import CoreConclusion
from core.entities.thought_view import ThoughtView
from core.search.question_slot_planner import QuestionSlotPlan, QuestionSlotPlanner, QuestionSlotPlannerError
from core.search.search_scope_gate import SearchScopeGate, SearchScopeGateDecision, SearchScopeGateError
from core.search.search_coverage_refiner import (
    SearchCoverageRefiner,
    SearchCoverageRefinerError,
    SlotCoverageSupport,
)
from core.search.search_need_evaluator import SearchNeedDecision, SearchNeedEvaluator
from core.search.search_query_planner import SearchPlan, SearchQueryPlanner, SearchQueryPlannerError


@dataclass(slots=True)
class SearchEvidence:
    title: str
    snippet: str
    url: str
    provider: str = 'wikipedia'
    domain: str = ''
    source_type: str = 'search'
    claim_domain: str = 'world_fact'
    trust_hint: str = ''
    source_provenance: str = ''
    passages: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text_for_graph(self) -> str:
        if self.passages:
            return f'{self.title}: {self.passages[0]}'
        if self.snippet:
            return f'{self.title}: {self.snippet}'
        return self.title


@dataclass(slots=True)
class SearchBackendResult:
    results: list[SearchEvidence] = field(default_factory=list)
    provider_errors: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class SearchRunResult:
    attempted: bool
    decision: SearchNeedDecision
    slot_plan: QuestionSlotPlan | None = None
    plan: SearchPlan | None = None
    results: list[SearchEvidence] = field(default_factory=list)
    error: str | None = None
    planning_attempted: bool = False
    provider_errors: list[dict[str, Any]] = field(default_factory=list)


class SearchBackend(Protocol):
    def search(
        self,
        query: str,
        *,
        max_results: int,
        timeout_seconds: float,
    ) -> SearchBackendResult | list[SearchEvidence]: ...


@dataclass(slots=True)
class WikipediaSearchBackend:
    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> SearchBackendResult:
        provider_errors: list[dict[str, Any]] = []
        ko_results, ko_error = self._search_wikipedia(query, lang='ko', max_results=max_results, timeout_seconds=timeout_seconds)
        if ko_error:
            provider_errors.append({'provider': 'wikipedia-ko', 'query': query, 'error': ko_error})
        if ko_results:
            return SearchBackendResult(results=ko_results[:max_results], provider_errors=provider_errors)

        en_results, en_error = self._search_wikipedia(query, lang='en', max_results=max_results, timeout_seconds=timeout_seconds)
        if en_error:
            provider_errors.append({'provider': 'wikipedia-en', 'query': query, 'error': en_error})
        return SearchBackendResult(results=en_results[:max_results], provider_errors=provider_errors)

    def _search_wikipedia(
        self,
        query: str,
        *,
        lang: str,
        max_results: int,
        timeout_seconds: float,
    ) -> tuple[list[SearchEvidence], str | None]:
        base = f'https://{lang}.wikipedia.org/w/api.php?action=opensearch&search={quote(query)}&limit={max_results}&namespace=0&format=json'
        request = Request(base, headers={'User-Agent': 'MK5-SearchSidecar/0.1'})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            return [], str(exc)

        titles = payload[1] if len(payload) > 1 else []
        descriptions = payload[2] if len(payload) > 2 else []
        urls = payload[3] if len(payload) > 3 else []
        evidences: list[SearchEvidence] = []
        for index, title in enumerate(titles[:max_results]):
            snippet = descriptions[index] if index < len(descriptions) else ''
            url = urls[index] if index < len(urls) else ''
            if not title:
                continue
            passages = self._fetch_summary_passages(title=str(title), lang=lang, timeout_seconds=timeout_seconds)
            evidences.append(
                SearchEvidence(
                    title=str(title),
                    snippet=str(snippet or ''),
                    url=str(url or ''),
                    provider=f'wikipedia-{lang}',
                    domain='wikipedia.org',
                    trust_hint='reference',
                    source_provenance=f'wikipedia:{lang}',
                    passages=passages,
                    metadata={'query': query, 'lang': lang},
                )
            )
        return evidences, None

    def _fetch_summary_passages(self, *, title: str, lang: str, timeout_seconds: float) -> list[str]:
        safe_title = quote(title.replace(' ', '_'))
        summary_url = f'https://{lang}.wikipedia.org/api/rest_v1/page/summary/{safe_title}'
        request = Request(summary_url, headers={'User-Agent': 'MK5-SearchSidecar/0.1'})
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except Exception:
            return []
        extract = ' '.join(str(payload.get('extract') or '').split()).strip()
        return [extract] if extract else []


@dataclass(slots=True)
class DuckDuckGoSearchBackend:
    search_url: str = 'https://html.duckduckgo.com/html/'

    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> SearchBackendResult:
        request = Request(
            f'{self.search_url}?q={quote(query)}',
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; MK5-TrustedSearch/0.1)',
                'Accept-Language': 'ko,en;q=0.8',
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read().decode('utf-8', errors='ignore')
        except Exception as exc:
            return SearchBackendResult(
                results=[],
                provider_errors=[{'provider': 'duckduckgo-web', 'query': query, 'error': str(exc)}],
            )

        results = self._parse_results(payload, max_results=max_results)
        for item in results:
            item.metadata = {**item.metadata, 'query': query}
        return SearchBackendResult(results=results)

    def _parse_results(self, payload: str, *, max_results: int) -> list[SearchEvidence]:
        anchor_pattern = re.compile(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>|<div[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</div>',
            re.IGNORECASE | re.DOTALL,
        )

        snippets = [
            self._clean_html(match.group(1) or match.group(2) or '')
            for match in snippet_pattern.finditer(payload)
        ]

        evidences: list[SearchEvidence] = []
        seen_urls: set[str] = set()
        for index, match in enumerate(anchor_pattern.finditer(payload)):
            raw_url = match.group(1)
            resolved_url = self._resolve_result_url(raw_url)
            if not resolved_url or resolved_url in seen_urls:
                continue
            seen_urls.add(resolved_url)

            title = self._clean_html(match.group(2))
            if not title:
                continue
            snippet = snippets[index] if index < len(snippets) else ''
            domain = self._normalize_domain(resolved_url)
            evidences.append(
                SearchEvidence(
                    title=title,
                    snippet=snippet,
                    url=resolved_url,
                    provider='duckduckgo-web',
                    domain=domain,
                    trust_hint='web_search',
                    source_provenance=f'web:duckduckgo:{domain or "unknown"}',
                    metadata={'domain': domain},
                )
            )
            if len(evidences) >= max_results:
                break
        return evidences

    def _resolve_result_url(self, raw_url: str) -> str:
        decoded = html.unescape(raw_url or '').strip()
        if not decoded:
            return ''
        absolute = urljoin('https://duckduckgo.com', decoded)
        parsed = urlparse(absolute)
        if 'duckduckgo.com' in (parsed.hostname or '') and parsed.path.startswith('/l/'):
            target = parse_qs(parsed.query).get('uddg', [])
            if target:
                return unquote(target[0])
        return absolute

    def _clean_html(self, value: str) -> str:
        text = re.sub(r'<[^>]+>', ' ', value or '')
        text = html.unescape(text)
        return ' '.join(text.split()).strip()

    def _normalize_domain(self, url: str) -> str:
        hostname = (urlparse(url).hostname or '').lower().strip()
        if hostname.startswith('www.'):
            hostname = hostname[4:]
        return hostname


@dataclass(slots=True)
class CompositeSearchBackend:
    backends: list[SearchBackend] = field(
        default_factory=lambda: [
            WikipediaSearchBackend(),
            DuckDuckGoSearchBackend(),
        ]
    )

    def search(self, query: str, *, max_results: int, timeout_seconds: float) -> SearchBackendResult:
        merged: list[SearchEvidence] = []
        provider_errors: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        per_backend_limit = max(1, max_results)
        for backend in self.backends:
            response = backend.search(query, max_results=per_backend_limit, timeout_seconds=timeout_seconds)
            normalized = self._normalize_response(response)
            provider_errors.extend(normalized.provider_errors)
            for item in normalized.results:
                title_key = item.title.strip().lower()
                url_key = item.url.strip().lower()
                if (url_key and url_key in seen_urls) or (title_key and title_key in seen_titles):
                    continue
                if url_key:
                    seen_urls.add(url_key)
                if title_key:
                    seen_titles.add(title_key)
                merged.append(item)
                if len(merged) >= max_results:
                    return SearchBackendResult(results=merged, provider_errors=provider_errors)
        return SearchBackendResult(results=merged, provider_errors=provider_errors)

    def _normalize_response(self, response: SearchBackendResult | list[SearchEvidence]) -> SearchBackendResult:
        if isinstance(response, SearchBackendResult):
            return response
        return SearchBackendResult(results=list(response or []))


@dataclass(slots=True)
class SearchSidecar:
    max_results: int = SEARCH_MAX_RESULTS
    timeout_seconds: float = SEARCH_BACKEND_TIMEOUT_SECONDS
    need_evaluator: SearchNeedEvaluator = field(default_factory=SearchNeedEvaluator)
    scope_gate: SearchScopeGate = field(default_factory=SearchScopeGate)
    slot_planner: QuestionSlotPlanner = field(default_factory=QuestionSlotPlanner)
    query_planner: SearchQueryPlanner = field(default_factory=SearchQueryPlanner)
    coverage_refiner: SearchCoverageRefiner = field(default_factory=SearchCoverageRefiner)
    backend: SearchBackend = field(default_factory=CompositeSearchBackend)
    evidence_passage_limit: int = 2
    evidence_fetch_timeout_seconds: float = 3.0

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
        coarse_decision = self.need_evaluator.evaluate(message=message, thought_view=thought_view, conclusion=conclusion)
        scope_gate_decision: SearchScopeGateDecision | None = None
        scope_gate_error: str | None = None

        if self._can_attempt_scope_gate(model_name):
            try:
                scope_gate_decision = self.scope_gate.decide(
                    model_name=model_name,
                    message=message,
                    thought_view=thought_view,
                    conclusion=conclusion,
                    target_terms=coarse_decision.target_terms,
                )
            except SearchScopeGateError as exc:
                scope_gate_error = str(exc)

        scope_gate_metadata = self._build_scope_gate_metadata(
            scope_gate_decision=scope_gate_decision,
            scope_gate_error=scope_gate_error,
        )

        if scope_gate_decision is not None and not scope_gate_decision.needs_external_search:
            blocked_decision = self._decision_after_scope_gate_block(
                coarse_decision=coarse_decision,
                scope_gate_decision=scope_gate_decision,
            )
            blocked_decision.metadata = {**blocked_decision.metadata, **scope_gate_metadata}
            return SearchRunResult(attempted=False, decision=blocked_decision, planning_attempted=False)

        try:
            slot_plan = self.slot_planner.plan(
                model_name=model_name,
                message=message,
                thought_view=thought_view,
                conclusion=conclusion,
                target_terms=coarse_decision.target_terms,
            )
        except QuestionSlotPlannerError as exc:
            failed_decision = self._decision_after_slot_planner_failure(coarse_decision, conclusion=conclusion)
            failed_decision.metadata = {**failed_decision.metadata, **scope_gate_metadata}
            return SearchRunResult(
                attempted=False,
                decision=failed_decision,
                error=str(exc),
                planning_attempted=True,
            )

        decision = self.need_evaluator.evaluate(
            message=message,
            thought_view=thought_view,
            conclusion=conclusion,
            slot_plan=slot_plan,
        )
        decision.metadata = {**decision.metadata, **scope_gate_metadata}
        if not decision.need_search:
            return SearchRunResult(attempted=False, decision=decision, slot_plan=slot_plan, planning_attempted=True)

        try:
            plan = self.query_planner.plan(
                model_name=model_name,
                message=message,
                thought_view=thought_view,
                conclusion=conclusion,
                decision=decision,
            )
        except SearchQueryPlannerError as exc:
            return SearchRunResult(attempted=False, decision=decision, slot_plan=slot_plan, error=str(exc), planning_attempted=True)

        results, provider_errors = self._execute_plan(plan)
        post_search_decision = decision
        if results:
            try:
                analysis = self.coverage_refiner.refine(
                    model_name=model_name,
                    message=message,
                    conclusion=conclusion,
                    slot_plan=slot_plan,
                    evidences=results,
                )
                post_search_decision = self._decision_after_search_refinement(
                    original_decision=decision,
                    slot_plan=slot_plan,
                    slot_supports=analysis.slot_supports,
                    reason=analysis.reason,
                )
            except SearchCoverageRefinerError as exc:
                provider_errors.append({'provider': 'search-coverage-refiner', 'query': message, 'error': str(exc)})
        return SearchRunResult(
            attempted=True,
            decision=post_search_decision,
            slot_plan=slot_plan,
            plan=plan,
            results=results,
            planning_attempted=True,
            provider_errors=provider_errors,
        )

    def search(self, message: str, thought_view: ThoughtView, conclusion: CoreConclusion, *, model_name: str) -> list[SearchEvidence]:
        return self.run(message=message, thought_view=thought_view, conclusion=conclusion, model_name=model_name).results

    def _can_attempt_scope_gate(self, model_name: str) -> bool:
        token = str(model_name or '').strip()
        return bool(token and token != 'mk5-graph-core')

    def _build_scope_gate_metadata(
        self,
        *,
        scope_gate_decision: SearchScopeGateDecision | None,
        scope_gate_error: str | None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if scope_gate_decision is not None or scope_gate_error is not None:
            metadata['scope_gate_attempted'] = True
        if scope_gate_decision is not None:
            metadata['scope_gate'] = scope_gate_decision.to_metadata()
        if scope_gate_error:
            metadata['scope_gate_error'] = scope_gate_error
        return metadata

    def _decision_after_scope_gate_block(
        self,
        *,
        coarse_decision: SearchNeedDecision,
        scope_gate_decision: SearchScopeGateDecision,
    ) -> SearchNeedDecision:
        return SearchNeedDecision(
            need_search=False,
            reason='external_grounding_not_needed',
            gap_summary=scope_gate_decision.reason,
            target_node_ids=list(coarse_decision.target_node_ids),
            target_terms=list(coarse_decision.target_terms),
            requested_slots=list(coarse_decision.requested_slots),
            covered_slots=list(coarse_decision.covered_slots),
            missing_slots=list(coarse_decision.missing_slots),
            slot_supports=list(coarse_decision.slot_supports),
            metadata={
                **coarse_decision.metadata,
                'scope_gate_blocked': True,
            },
        )

    def _decision_after_slot_planner_failure(
        self,
        coarse_decision: SearchNeedDecision,
        *,
        conclusion: CoreConclusion,
    ) -> SearchNeedDecision:
        target_terms = list(coarse_decision.target_terms)
        complex_request = len(target_terms) >= 3 or len(conclusion.activated_concepts) >= 4
        if complex_request:
            return SearchNeedDecision(
                need_search=True,
                reason='slot_planner_failed_needs_grounding',
                gap_summary='질문 구조 분해는 실패했지만 다중 개념/비교 요청이라 외부 근거 확인이 여전히 필요하다.',
                target_node_ids=list(coarse_decision.target_node_ids),
                target_terms=target_terms,
                requested_slots=list(coarse_decision.requested_slots),
                covered_slots=list(coarse_decision.covered_slots),
                missing_slots=list(coarse_decision.missing_slots),
                slot_supports=list(coarse_decision.slot_supports),
                metadata={**coarse_decision.metadata, 'slot_planner_failed': True},
            )
        return coarse_decision

    def _execute_plan(self, plan: SearchPlan) -> tuple[list[SearchEvidence], list[dict[str, Any]]]:
        aggregated: list[SearchEvidence] = []
        provider_errors: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        for query in plan.queries:
            response = self.backend.search(query, max_results=self.max_results, timeout_seconds=self.timeout_seconds)
            normalized = self._normalize_backend_response(response, query=query)
            provider_errors.extend(normalized.provider_errors)
            for item in normalized.results:
                title_key = item.title.strip().lower()
                url_key = item.url.strip().lower()
                if (url_key and url_key in seen_urls) or (title_key and title_key in seen_titles):
                    continue
                if url_key:
                    seen_urls.add(url_key)
                if title_key:
                    seen_titles.add(title_key)
                item.metadata = {**item.metadata, 'planned_query': query}
                self._ensure_evidence_passages(item, query=query)
                aggregated.append(item)
                if len(aggregated) >= self.max_results:
                    return aggregated, provider_errors
        return aggregated, provider_errors

    def _ensure_evidence_passages(self, item: SearchEvidence, *, query: str) -> None:
        passages = self._dedupe_passages(list(item.passages or []))
        if not passages and item.url and self._should_fetch_passages(item.url):
            fetched = self._fetch_passages_from_url(item.url, query=query, title=item.title)
            passages.extend(fetched)
        if not passages and item.snippet:
            passages.append(item.snippet)
        item.passages = self._dedupe_passages(passages)[: self.evidence_passage_limit]

    def _should_fetch_passages(self, url: str) -> bool:
        parsed = urlparse(url)
        hostname = (parsed.hostname or '').lower().strip()
        if parsed.scheme not in {'http', 'https'}:
            return False
        if not hostname:
            return False
        if hostname == 'localhost' or hostname.endswith('.test'):
            return False
        return True

    def _fetch_passages_from_url(self, url: str, *, query: str, title: str) -> list[str]:
        request = Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; MK5-SearchSidecar/0.1)',
                'Accept-Language': 'ko,en;q=0.8',
            },
        )
        timeout = max(0.5, min(self.evidence_fetch_timeout_seconds, self.timeout_seconds))
        try:
            with urlopen(request, timeout=timeout) as response:
                content_type = str(response.headers.get('Content-Type') or '').lower()
                raw = response.read(250000)
        except Exception:
            return []

        text = self._decode_response_bytes(raw)
        if 'html' in content_type or '<html' in text.lower():
            return self._extract_html_passages(text=text, query=query, title=title)
        return self._extract_text_passages(text=text, query=query, title=title)

    def _decode_response_bytes(self, raw: bytes) -> str:
        for encoding in ('utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin-1'):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', errors='ignore')

    def _extract_html_passages(self, *, text: str, query: str, title: str) -> list[str]:
        text = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', ' ', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'</?(p|div|br|li|section|article|h1|h2|h3|h4|h5|h6|tr|ul|ol)[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = html.unescape(text)
        return self._extract_text_passages(text=text, query=query, title=title)

    def _extract_text_passages(self, *, text: str, query: str, title: str) -> list[str]:
        candidates: list[str] = []
        for raw_line in re.split(r'\n+', text):
            normalized = ' '.join(str(raw_line or '').split()).strip()
            if len(normalized) < 40:
                continue
            candidates.append(normalized)
        if not candidates:
            return []
        tokens = self._query_tokens([query, title])
        scored: list[tuple[int, int, str]] = []
        for candidate in candidates[:80]:
            lowered = candidate.lower()
            score = sum(1 for token in tokens if token in lowered)
            scored.append((score, len(candidate), candidate))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        ordered = [item[2] for item in scored if item[0] > 0]
        if not ordered:
            ordered = [item[2] for item in scored]
        return self._dedupe_passages(ordered)[: self.evidence_passage_limit]

    def _query_tokens(self, values: list[str]) -> list[str]:
        tokens: list[str] = []
        for value in values:
            for token in re.split(r'\s+', str(value or '').lower()):
                token = token.strip()
                if len(token) < 2 or token in tokens:
                    continue
                tokens.append(token)
        return tokens

    def _dedupe_passages(self, passages: list[str]) -> list[str]:
        deduped: list[str] = []
        for passage in passages:
            normalized = ' '.join(str(passage or '').split()).strip()
            if not normalized or normalized in deduped:
                continue
            deduped.append(normalized)
        return deduped

    def _normalize_backend_response(
        self,
        response: SearchBackendResult | list[SearchEvidence],
        *,
        query: str,
    ) -> SearchBackendResult:
        if isinstance(response, SearchBackendResult):
            return response
        return SearchBackendResult(results=list(response or []), provider_errors=[])

    def _decision_after_search_refinement(
        self,
        *,
        original_decision: SearchNeedDecision,
        slot_plan: QuestionSlotPlan,
        slot_supports: list[SlotCoverageSupport],
        reason: str,
    ) -> SearchNeedDecision:
        slot_by_label = {slot.label: slot for slot in slot_plan.requested_slots}
        covered = [
            self.need_evaluator._slot_dict(slot_by_label[item.slot_label])
            for item in slot_supports
            if item.supported and item.slot_label in slot_by_label
        ]
        missing = [
            self.need_evaluator._slot_dict(slot_by_label[item.slot_label])
            for item in slot_supports
            if not item.supported and item.slot_label in slot_by_label
        ]
        support_payload = [
            {
                'slot_label': item.slot_label,
                'supported': item.supported,
                'evidence_indices': list(item.evidence_indices),
            }
            for item in slot_supports
            if item.slot_label in slot_by_label
        ]
        if not missing and len(covered) < len(slot_plan.requested_slots):
            missing = [
                self.need_evaluator._slot_dict(slot)
                for slot in slot_plan.requested_slots
                if slot.label not in {item.slot_label for item in slot_supports if item.supported}
            ]
        need_search = bool(missing)
        gap_summary = (
            f'검색 결과를 반영해도 아직 비어 있는 슬롯이 있다: {", ".join(item["label"] for item in missing[:4])}'
            if need_search
            else '검색 결과 기준으로 요청 슬롯이 모두 확인되었다.'
        )
        return SearchNeedDecision(
            need_search=need_search,
            reason='post_search_missing_slot_grounding' if need_search else 'post_search_slot_coverage_sufficient',
            gap_summary=gap_summary,
            target_node_ids=list(original_decision.target_node_ids),
            target_terms=list(original_decision.target_terms),
            requested_slots=list(original_decision.requested_slots),
            covered_slots=covered,
            missing_slots=missing,
            slot_supports=support_payload,
            metadata={
                **original_decision.metadata,
                'post_search_refined': True,
                'post_search_refiner_reason': reason,
            },
        )
