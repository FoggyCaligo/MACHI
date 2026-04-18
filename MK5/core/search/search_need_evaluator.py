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
    slot_supports: list[dict[str, Any]] = field(default_factory=list)
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
        scope_nodes = self._grounding_scope_nodes(thought_view)
        target_terms = self._collect_target_terms(thought_view, scope_nodes=scope_nodes)
        target_node_ids = [node.id for node in scope_nodes if node.id is not None]

        if slot_plan is None:
            missing_terms = [term for term in target_terms if not self._has_entity_grounding(scope_nodes, term)]
            need_search = bool(missing_terms)
            if need_search:
                preview = ', '.join(missing_terms[:4])
                return SearchNeedDecision(
                    need_search=True,
                    reason='missing_concept_grounding',
                    gap_summary=f'현재 질문 핵심 개념 중 아직 grounding이 없는 항목이 있어 외부 검색이 필요하다: {preview}',
                    target_node_ids=target_node_ids,
                    target_terms=target_terms,
                    requested_slots=[self._slot_dict(RequestedSlot(kind='entity', entity=term)) for term in target_terms],
                    covered_slots=[self._slot_dict(RequestedSlot(kind='entity', entity=term)) for term in target_terms if term not in missing_terms],
                    missing_slots=[self._slot_dict(RequestedSlot(kind='entity', entity=term)) for term in missing_terms],
                    slot_supports=[
                        {
                            'slot_label': term,
                            'supported': term not in missing_terms,
                            'evidence_indices': [],
                        }
                        for term in target_terms
                    ],
                    metadata={
                        'focus_mode': 'topic_terms_first',
                        'grounding_scope_node_ids': target_node_ids,
                    },
                )
            return SearchNeedDecision(
                need_search=False,
                reason='concept_grounding_sufficient',
                gap_summary='현재 질문 핵심 개념은 이미 기존 그래프의 grounding 범위 안에 있다.',
                target_node_ids=target_node_ids,
                target_terms=target_terms,
                requested_slots=[self._slot_dict(RequestedSlot(kind='entity', entity=term)) for term in target_terms],
                covered_slots=[self._slot_dict(RequestedSlot(kind='entity', entity=term)) for term in target_terms],
                missing_slots=[],
                slot_supports=[
                    {'slot_label': term, 'supported': True, 'evidence_indices': []}
                    for term in target_terms
                ],
                metadata={
                    'focus_mode': 'topic_terms_first',
                    'grounding_scope_node_ids': target_node_ids,
                },
            )

        requested_slots = [self._slot_dict(slot) for slot in slot_plan.requested_slots]
        covered: list[RequestedSlot] = []
        missing: list[RequestedSlot] = []
        grounded_entities: dict[str, bool] = {entity: self._has_entity_grounding(scope_nodes, entity) for entity in slot_plan.entities}
        for slot in slot_plan.requested_slots:
            if self._slot_is_covered(scope_nodes, slot, grounded_entities):
                covered.append(slot)
            else:
                missing.append(slot)

        need_search = bool(missing)
        if need_search:
            reason = 'missing_slot_grounding'
            missing_labels = ', '.join(slot.label for slot in missing[:4])
            gap_summary = (
                '현재 질문의 일부 요구 슬롯이 아직 비어 있어 외부 근거가 더 필요하다: '
                f'{missing_labels}'
            )
        else:
            reason = 'slot_coverage_sufficient'
            gap_summary = '현재 질문에서 요구한 개념과 비교 축이 현재 그래프 범위 안에서 이미 충분히 커버됐다.'

        return SearchNeedDecision(
            need_search=need_search,
            reason=reason,
            gap_summary=gap_summary,
            target_node_ids=target_node_ids,
            target_terms=self._merge_unique(target_terms + list(dict.fromkeys([*slot_plan.entities, *slot_plan.aspects]))),
            requested_slots=requested_slots,
            covered_slots=[self._slot_dict(slot) for slot in covered],
            missing_slots=[self._slot_dict(slot) for slot in missing],
            slot_supports=[
                {
                    'slot_label': slot.label,
                    'supported': slot.label not in {item.label for item in missing},
                    'evidence_indices': [],
                }
                for slot in slot_plan.requested_slots
            ],
            metadata={
                'grounding_scope_node_ids': target_node_ids,
                'slot_plan_reason': slot_plan.reason,
                'grounded_entities': grounded_entities,
                'focus_mode': 'topic_terms_first',
            },
        )

    def _grounding_scope_nodes(self, thought_view: ThoughtView) -> list[Node]:
        metadata = thought_view.metadata or {}
        current_root_event_id = metadata.get('current_root_event_id')
        scope: list[Node] = []
        seen_ids: set[int] = set()
        for node in thought_view.nodes:
            if node.id is None or node.id in seen_ids:
                continue
            if current_root_event_id is not None and node.created_from_event_id == current_root_event_id:
                continue
            scope.append(node)
            seen_ids.add(node.id)
            if len(scope) >= self.grounding_scope_limit:
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
        return bool(
            source_type and source_type not in {'user', 'assistant'}
            and node.trust_score >= 0.8
            and node.stability_score >= 0.7
        )

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
        passages = payload.get('passages') or []
        if isinstance(passages, list):
            parts.extend(str(item or '') for item in passages)
        aliases = payload.get('raw_aliases') or []
        if isinstance(aliases, list):
            parts.extend(str(item or '') for item in aliases)
        return self._norm(' '.join(parts))

    def _collect_target_terms(self, thought_view: ThoughtView, *, scope_nodes: list[Node]) -> list[str]:
        metadata = thought_view.metadata or {}
        topic_terms = self._normalize_terms(metadata.get('current_topic_terms') or [])
        if topic_terms:
            return topic_terms[:6]
        terms: list[str] = []
        for activated in thought_view.seed_nodes:
            self._append_term(terms, getattr(activated.node, 'normalized_value', None))
        for node in scope_nodes:
            self._append_term(terms, getattr(node, 'normalized_value', None))
        return terms[:6]

    def _append_term(self, terms: list[str], value: object) -> None:
        token = ' '.join(str(value or '').split()).strip()
        if not token or len(token) < 2 or len(token) > 80:
            return
        if token in terms:
            return
        terms.append(token)

    def _normalize_terms(self, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in values or []:
            self._append_term(normalized, item)
        return normalized

    def _merge_unique(self, values: list[str]) -> list[str]:
        merged: list[str] = []
        for item in values:
            self._append_term(merged, item)
        return merged[:8]

    def _slot_dict(self, slot: RequestedSlot) -> dict[str, str]:
        return {'kind': slot.kind, 'entity': slot.entity, 'aspect': slot.aspect, 'label': slot.label}

    def _norm(self, value: str) -> str:
        return ' '.join(str(value or '').split()).strip().lower()
