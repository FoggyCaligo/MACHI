from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.search.search_need_evaluator import SearchNeedDecision


class SearchQueryPlannerError(RuntimeError):
    pass


@dataclass(slots=True)
class SearchPlan:
    queries: list[str]
    reason: str
    focus_terms: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchQueryPlanner:
    max_queries: int = 6

    def plan(
        self,
        *,
        model_name: str,
        message: str,
        decision: SearchNeedDecision,
    ) -> SearchPlan:
        term_states = list(decision.metadata.get('term_states') or [])
        focus_terms: list[str] = []
        freshness_map: dict[str, str] = {}
        for item in term_states:
            term = ' '.join(str(item.get('term') or '').split()).strip()
            state = str(item.get('state') or '').strip()
            if not term or state == 'grounded_and_usable' or state == 'local_only':
                continue
            if term in focus_terms:
                continue
            focus_terms.append(term)
            freshness_map[term] = str(item.get('freshness_kind') or 'unknown').strip()
            if len(focus_terms) >= self.max_queries:
                break
        if not focus_terms:
            raise SearchQueryPlannerError('no concept queries to search')
        return SearchPlan(
            queries=list(focus_terms),
            reason='usable하지 않은 핵심 meaning unit을 개별 검색 쿼리로 발행한다.',
            focus_terms=list(focus_terms),
            metadata={
                'issued_slot_queries': [
                    {'entity': term, 'aspects': [], 'query': term, 'freshness_kind': freshness_map.get(term, 'unknown')}
                    for term in focus_terms
                ],
                'planned_aspect_extraction': [],
            },
        )
