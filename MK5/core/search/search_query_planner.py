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
        missing_slots = decision.missing_slots or []
        if not missing_slots:
            raise SearchQueryPlannerError('no missing slots to search')

        grouped: dict[str, dict[str, Any]] = {}
        for slot in missing_slots:
            entity = ' '.join(str(slot.get('entity') or '').split()).strip()
            aspect = ' '.join(str(slot.get('aspect') or '').split()).strip()
            if not entity:
                continue
            bucket = grouped.setdefault(entity, {'aspects': []})
            if aspect and aspect not in bucket['aspects']:
                bucket['aspects'].append(aspect)

        queries: list[str] = []
        issued_slot_queries: list[dict[str, Any]] = []
        planned_aspect_extraction: list[dict[str, Any]] = []
        grounding_queries: list[str] = []
        comparison_queries: list[str] = []

        for entity, info in grouped.items():
            aspects = list(info['aspects'][:4])
            planned_aspect_extraction.append({'entity': entity, 'aspects': list(aspects)})
            for query in self._build_queries_for_entity(entity=entity, aspects=aspects):
                if query in queries:
                    continue
                queries.append(query)
                grounding_queries.append(query)
                issued_slot_queries.append(
                    {
                        'entity': entity,
                        'aspects': list(aspects),
                        'query': query,
                    }
                )
                if len(queries) >= self.max_queries:
                    break
            if len(queries) >= self.max_queries:
                break

        if not queries:
            raise SearchQueryPlannerError('search planner produced no usable entity queries')

        focus_terms = list(grouped.keys())[:6]
        reason = 'missing slot의 핵심 entity를 개별 개념 쿼리로 발행하도록 계획했다.'
        return SearchPlan(
            queries=queries,
            reason=reason,
            focus_terms=focus_terms,
            metadata={
                'issued_slot_queries': issued_slot_queries,
                'planned_aspect_extraction': planned_aspect_extraction,
                'missing_slots': missing_slots,
                'grounding_queries': grounding_queries,
                'comparison_queries': comparison_queries,
            },
        )

    def _build_queries_for_entity(self, *, entity: str, aspects: list[str]) -> list[str]:
        queries: list[str] = []
        entity_only = self._compact_query([entity])
        if entity_only:
            queries.append(entity_only)
        return queries

    def _compact_query(self, parts: list[str]) -> str:
        tokens: list[str] = []
        for part in parts:
            token = ' '.join(str(part or '').split()).strip()
            if not token or token in tokens:
                continue
            tokens.append(token)
        return ' '.join(tokens)
