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
    max_queries: int = 8

    def plan(
        self,
        *,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        decision: SearchNeedDecision,
    ) -> SearchPlan:
        missing_concepts = list(decision.metadata.get('missing_focus_terms') or decision.metadata.get('missing_terms') or [])
        if not missing_concepts:
            raise SearchQueryPlannerError('no missing concepts to search')
        queries: list[str] = []
        for term in missing_concepts:
            token = ' '.join(str(term or '').split()).strip()
            if not token or token in queries:
                continue
            queries.append(token)
            if len(queries) >= self.max_queries:
                break
        if not queries:
            raise SearchQueryPlannerError('search planner produced no usable concept queries')
        return SearchPlan(
            queries=queries,
            reason='grounding이 없는 normalized concept를 개별 검색 쿼리로 발행한다.',
            focus_terms=queries[:],
            metadata={
                'missing_concepts': missing_concepts,
                'query_mode': 'individual_concepts',
            },
        )
