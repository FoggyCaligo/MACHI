from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.entities.conclusion import CoreConclusion
from core.entities.thought_view import ThoughtView
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
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        decision: SearchNeedDecision,
    ) -> SearchPlan:
        missing_terms = list(decision.metadata.get('missing_terms') or [])
        focus_terms = missing_terms or list(decision.target_terms)
        queries: list[str] = []
        for term in focus_terms:
            token = ' '.join(str(term or '').split()).strip()
            if not token or token in queries:
                continue
            queries.append(token)
            if len(queries) >= self.max_queries:
                break
        if not queries:
            raise SearchQueryPlannerError('no concept queries to search')
        return SearchPlan(
            queries=queries,
            reason='grounding이 없는 normalized concept를 개별 검색 쿼리로 발행한다.',
            focus_terms=list(focus_terms[: self.max_queries]),
            metadata={
                'issued_slot_queries': [
                    {'entity': term, 'aspects': [], 'query': term}
                    for term in queries
                ],
                'planned_aspect_extraction': [],
            },
        )
