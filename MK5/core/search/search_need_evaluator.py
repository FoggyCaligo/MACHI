from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.entities.conclusion import CoreConclusion
from core.entities.node import Node
from core.entities.thought_view import ThoughtView
from core.search.question_slot_planner import QuestionSlotPlan, RequestedSlot


@dataclass(slots=True)
class SearchNeedDecision:
    need_search: bool
    reason: str
    gap_summary: str
    target_node_ids: list[int] = field(default_factory=list)
    target_terms: list[str] = field(default_factory=list)
    requested_slots: list[dict[str, str]] = field(default_factory=list)
    covered_slots: list[dict[str, str]] = field(default_factory=list)
    missing_slots: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchNeedEvaluator:
    grounding_scope_limit: int = 8

    def evaluate(
        self,
        *,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        slot_plan: QuestionSlotPlan | None = None,
    ) -> SearchNeedDecision:
        explicit_memory_probe = conclusion.inferred_intent == 'memory_probe'
        scope_nodes = self._grounding_scope_nodes(thought_view)
        target_terms = self._collect_target_terms(thought_view, scope_nodes=scope_nodes)
        target_node_ids = [node.id for node in scope_nodes if node.id is not None]

        if explicit_memory_probe:
            return SearchNeedDecision(
                need_search=False,
                reason='memory_probe_no_external_search',
                gap_summary='기억 여부를 묻는 질문이라 외부 검색보다 현재 세션 상태를 직접 답하는 편이 맞다.',
                target_node_ids=target_node_ids,
                target_terms=target_terms,
                metadata={'grounding_scope_node_ids': target_node_ids},
            )

        if slot_plan is None:
            has_seed_coverage = len(thought_view.seed_nodes) > 0
            concept_edge_count = sum(
                1 for e in thought_view.edges
                if e.edge_family == 'concept' and e.is_active
            )
            sparse_graph = (
                not has_seed_coverage
                and concept_edge_count == 0
                and len(conclusion.activated_concepts) <= 2
                and len(conclusion.key_relations) <= 1
            )
            unresolved_conflict = bool(conclusion.detected_conflicts)
            need_search = sparse_graph or unresolved_conflict
            reason = 'graph_too_sparse_for_answer' if sparse_graph else 'graph_conflict_requires_grounding' if unresolved_conflict else 'graph_sufficient_without_search'
            gap_summary = (
                '현재 사고 그래프에 시드 노드가 없고 활성화된 개념 구조도 부족해 질문에 답할 근거가 충분하지 않다.' if sparse_graph else
                '현재 사고 그래프에 충돌이 남아 있어 외부 근거로 현재 주제를 확인할 필요가 있다.' if unresolved_conflict else
                '현재 활성화된 개념과 관계만으로도 질문에 직접 답할 수 있다.'
            )
            return SearchNeedDecision(
                need_search=need_search,
                reason=reason,
                gap_summary=gap_summary,
                target_node_ids=target_node_ids,
                target_terms=target_terms,
                metadata={
                    'fallback_mode': True,
                    'grounding_scope_node_ids': target_node_ids,
                },
            )

        requested_slots = [self._slot_dict(slot) for slot in slot_plan.requested_slots]
        covered: list[RequestedSlot] = []
        missing: list[RequestedSlot] = []
        grounded_entities: dict[str, bool] = {}
        for entity in slot_plan.entities:
            grounded_entities[entity] = self._has_entity_grounding(scope_nodes, entity)
        for slot in slot_plan.requested_slots:
            if self._slot_is_covered(scope_nodes, slot, grounded_entities):
                covered.append(slot)
            else:
                missing.append(slot)

        need_search = bool(missing)
        if need_search:
            reason = 'missing_slot_grounding'
            missing_labels = ', '.join(slot.label for slot in missing[:4])
            gap_summary = f'현재 질문의 일부 요구 슬롯이 아직 비어 있어 외부 근거가 더 필요하다: {missing_labels}'
        else:
            reason = 'slot_coverage_sufficient'
            gap_summary = '현재 질문에서 요구한 개념과 비교 축이 현재 그래프 범위 안에서 이미 충분히 커버된다.'

        return SearchNeedDecision(
            need_search=need_search,
            reason=reason,
            gap_summary=gap_summary,
            target_node_ids=target_node_ids,
            target_terms=list(dict.fromkeys([*slot_plan.entities, *slot_plan.aspects]))[:8],
            requested_slots=requested_slots,
            covered_slots=[self._slot_dict(slot) for slot in covered],
            missing_slots=[self._slot_dict(slot) for slot in missing],
            metadata={
                'grounding_scope_node_ids': target_node_ids,
                'slot_plan_reason': slot_plan.reason,
                'grounded_entities': grounded_entities,
            },
        )

    def _grounding_scope_nodes(self, thought_view: ThoughtView) -> list[Node]:
        scope: list[Node] = []
        seen_ids: set[int] = set()
        # Seed nodes are the current-question anchors, so never clip them by the generic scope limit.
        for activated in thought_view.seed_nodes:
            node = activated.node
            if node.id is None or node.id in seen_ids:
                continue
            scope.append(node)
            seen_ids.add(node.id)
        extra_budget = max(self.grounding_scope_limit, 0)
        added_extra = 0
        for node in thought_view.nodes:
            if node.id is None or node.id in seen_ids:
                continue
            scope.append(node)
            seen_ids.add(node.id)
            added_extra += 1
            if added_extra >= extra_budget:
                break
        return scope

    def _has_entity_grounding(self, nodes: list[Node], entity: str) -> bool:
        term = self._norm(entity)
        for node in nodes:
            if not self._node_has_grounding(node):
                continue
            text = self._node_text(node)
            if term and term in text:
                return True
        return False

    def _slot_is_covered(self, nodes: list[Node], slot: RequestedSlot, grounded_entities: dict[str, bool]) -> bool:
        if not grounded_entities.get(slot.entity, False):
            return False
        if slot.kind == 'entity' or not slot.aspect:
            return True
        entity = self._norm(slot.entity)
        aspect = self._norm(slot.aspect)
        for node in nodes:
            if not self._node_has_grounding(node):
                continue
            text = self._node_text(node)
            if entity in text and aspect in text:
                return True
        return False

    def _node_has_grounding(self, node: Node) -> bool:
        payload = node.payload if isinstance(node.payload, dict) else {}
        source_type = str(payload.get('source_type') or '').strip()
        claim_domain = str(payload.get('claim_domain') or '').strip()
        if source_type == 'search' or claim_domain == 'world_fact':
            return True
        return bool(source_type and source_type not in {'user', 'assistant'} and node.trust_score >= 0.8 and node.stability_score >= 0.7)

    def _node_text(self, node: Node) -> str:
        payload = node.payload if isinstance(node.payload, dict) else {}
        parts: list[str] = [
            str(getattr(node, 'normalized_value', '') or ''),
            str(getattr(node, 'raw_value', '') or ''),
            str(payload.get('title') or ''),
            str(payload.get('snippet') or ''),
            str(payload.get('content') or ''),
            str(payload.get('summary') or ''),
        ]
        aliases = payload.get('raw_aliases') or []
        if isinstance(aliases, list):
            parts.extend(str(item or '') for item in aliases)
        return self._norm(' '.join(parts))

    def _collect_target_terms(self, thought_view: ThoughtView, *, scope_nodes: list[Node]) -> list[str]:
        terms: list[str] = []
        for node in scope_nodes:
            self._append_term(terms, getattr(node, 'normalized_value', None))
            payload = node.payload if isinstance(node.payload, dict) else {}
            aliases = payload.get('raw_aliases', [])
            if isinstance(aliases, list):
                for alias in aliases:
                    self._append_term(terms, alias)
            if not getattr(node, 'normalized_value', None):
                self._append_term(terms, getattr(node, 'raw_value', None))
        return terms[:8]

    def _append_term(self, terms: list[str], value: object) -> None:
        token = ' '.join(str(value or '').split()).strip()
        if not token or len(token) < 2 or len(token) > 80:
            return
        if token in terms:
            return
        terms.append(token)

    def _slot_dict(self, slot: RequestedSlot) -> dict[str, str]:
        return {'kind': slot.kind, 'entity': slot.entity, 'aspect': slot.aspect, 'label': slot.label}

    def _norm(self, value: str) -> str:
        return ' '.join(str(value or '').split()).strip().lower()
