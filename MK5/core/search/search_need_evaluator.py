from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.entities.conclusion import CoreConclusion
from core.entities.node import Node
from core.entities.thought_view import ThoughtView


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
    grounding_scope_limit: int = 24

    def evaluate(
        self,
        *,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
        slot_plan: object | None = None,
    ) -> SearchNeedDecision:
        scope_nodes = self._grounding_scope_nodes(thought_view)
        target_terms = self._collect_target_terms(thought_view)
        target_node_ids = [node.id for node in scope_nodes if node.id is not None]
        grounded_terms = [term for term in target_terms if self._has_entity_grounding(scope_nodes, term)]
        missing_terms = [term for term in target_terms if term not in grounded_terms]

        need_search = bool(target_terms) and bool(missing_terms)
        if need_search:
            reason = 'missing_concept_grounding'
            gap_summary = (
                '현재 질문 핵심 개념 중 아직 grounding이 없는 항목이 있어 외부 검색이 필요하다: '
                + ', '.join(missing_terms[:4])
            )
        else:
            reason = 'concept_grounding_sufficient'
            gap_summary = '현재 질문 핵심 개념이 기존 그래프 안에서 이미 grounding 되어 있다.'

        requested_slots = [self._slot_dict(term) for term in target_terms]
        covered_slots = [self._slot_dict(term) for term in grounded_terms]
        missing_slots = [self._slot_dict(term) for term in missing_terms]
        slot_supports = [
            {
                'slot_label': term,
                'supported': term in grounded_terms,
                'evidence_indices': [],
            }
            for term in target_terms
        ]

        return SearchNeedDecision(
            need_search=need_search,
            reason=reason,
            gap_summary=gap_summary,
            target_node_ids=target_node_ids,
            target_terms=target_terms,
            requested_slots=requested_slots,
            covered_slots=covered_slots,
            missing_slots=missing_slots,
            slot_supports=slot_supports,
            metadata={
                'grounding_scope_node_ids': target_node_ids,
                'grounded_terms': grounded_terms,
                'missing_terms': missing_terms,
                'focus_source': 'final_statement_noun_phrases',
            },
        )

    def _grounding_scope_nodes(self, thought_view: ThoughtView) -> list[Node]:
        current_root_event_id = self._current_root_event_id(thought_view)
        grounded: list[Node] = []
        seen_ids: set[int] = set()
        for node in thought_view.nodes:
            if node.id is None or node.id in seen_ids:
                continue
            if current_root_event_id is not None and getattr(node, 'created_from_event_id', None) == current_root_event_id:
                continue
            if not self._node_has_grounding(node):
                continue
            grounded.append(node)
            seen_ids.add(node.id)
            if len(grounded) >= self.grounding_scope_limit:
                break
        return grounded

    def _collect_target_terms(self, thought_view: ThoughtView) -> list[str]:
        blocks = thought_view.seed_blocks or []
        if not blocks:
            return []

        last_statement_index = -1
        for index, block in enumerate(blocks):
            if block.block_kind == 'statement_phrase':
                last_statement_index = index

        focus_terms: list[str] = []
        if last_statement_index != -1:
            for block in blocks[last_statement_index + 1:]:
                if block.block_kind != 'noun_phrase':
                    continue
                self._append_term(focus_terms, block.normalized_text or block.text)

        if focus_terms:
            return focus_terms[:8]

        for block in blocks:
            if block.block_kind != 'noun_phrase':
                continue
            self._append_term(focus_terms, block.normalized_text or block.text)
        return focus_terms[:8]

    def _has_entity_grounding(self, nodes: list[Node], entity: str) -> bool:
        term = self._norm(entity)
        for node in nodes:
            text = self._node_text(node)
            if term and term in text:
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

    def _append_term(self, terms: list[str], value: object) -> None:
        token = self._norm(str(value or ''))
        if not token or len(token) < 2 or len(token) > 80:
            return
        if token in terms:
            return
        terms.append(token)

    def _slot_dict(self, term: str) -> dict[str, str]:
        return {'kind': 'entity', 'entity': term, 'aspect': '', 'label': term}

    def _current_root_event_id(self, thought_view: ThoughtView) -> int | None:
        metadata = thought_view.metadata if isinstance(thought_view.metadata, dict) else {}
        value = metadata.get('current_root_event_id')
        return value if isinstance(value, int) else None

    def _norm(self, value: str) -> str:
        return ' '.join(str(value or '').split()).strip().lower()
