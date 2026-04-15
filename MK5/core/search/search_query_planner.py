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
            kind = str(slot.get('kind') or '').strip() or 'entity'
            if not entity:
                continue
            bucket = grouped.setdefault(entity, {'needs_grounding': False, 'aspects': []})
            if kind == 'entity' or not aspect:
                bucket['needs_grounding'] = True
            if aspect and aspect not in bucket['aspects']:
                bucket['aspects'].append(aspect)

        queries: list[str] = []
        issued_slot_queries: list[dict[str, Any]] = []
        for entity, info in grouped.items():
            aspects = info['aspects'][:3]
            query = self._compact_query([entity, *aspects]) if aspects else self._compact_query([entity])
            if query and query not in queries:
                queries.append(query)
                issued_slot_queries.append({'entity': entity, 'aspects': aspects, 'query': query})
            if len(queries) >= self.max_queries:
                break

        if not queries:
            raise SearchQueryPlannerError('search planner produced no usable slot queries')

        focus_terms = list(grouped.keys())[:6]
        reason = '그래프에 비어 있는 슬롯만 골라 국소 검색 질의로 변환했다.'
        return SearchPlan(
            queries=queries,
            reason=reason,
            focus_terms=focus_terms,
            metadata={
                'issued_slot_queries': issued_slot_queries,
                'missing_slots': missing_slots,
            },
        )

    def _compact_query(self, parts: list[str]) -> str:
        tokens: list[str] = []
        for part in parts:
            token = ' '.join(str(part or '').split()).strip()
            if not token or token in tokens:
                continue
            tokens.append(token)
        return ' '.join(tokens)
