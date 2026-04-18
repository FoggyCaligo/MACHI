from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.cognition.meaning_block import MeaningBlock
from core.entities.node import Node


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
    def evaluate(
        self,
        *,
        message: str,
        meaning_blocks: list[MeaningBlock],
        resolved_nodes: dict[str, Node | None],
        current_root_event_id: int | None,
    ) -> SearchNeedDecision:
        keyword_blocks = self._collect_keyword_blocks(meaning_blocks)
        target_terms: list[str] = []
        target_node_ids: list[int] = []
        requested_slots: list[dict[str, str]] = []
        covered_slots: list[dict[str, str]] = []
        missing_slots: list[dict[str, str]] = []
        slot_supports: list[dict[str, Any]] = []
        grounded_terms: list[str] = []
        missing_terms: list[str] = []
        local_only_terms: list[str] = []
        term_states: list[dict[str, str]] = []

        for block in keyword_blocks:
            term = self._norm(block.normalized_text or block.text)
            if not term or term in target_terms:
                continue
            target_terms.append(term)
            slot = self._slot_dict(term)
            requested_slots.append(slot)
            node = resolved_nodes.get(term)
            if node is not None and node.id is not None and node.id not in target_node_ids:
                target_node_ids.append(node.id)

            search_policy = str(block.metadata.get('search_policy') or 'search_if_unusable').strip()
            freshness_kind = str(block.metadata.get('freshness_kind') or 'unknown').strip()
            state = self._classify_access_state(
                node=node,
                current_root_event_id=current_root_event_id,
                freshness_kind=freshness_kind,
                search_policy=search_policy,
            )
            term_states.append(
                {
                    'term': term,
                    'state': state,
                    'importance': str(block.metadata.get('importance') or 'secondary'),
                    'freshness_kind': freshness_kind,
                    'search_policy': search_policy,
                }
            )

            if state == 'grounded_and_usable':
                grounded_terms.append(term)
                covered_slots.append(slot)
                slot_supports.append({'slot_label': term, 'supported': True, 'evidence_indices': []})
            elif state == 'local_only':
                local_only_terms.append(term)
                covered_slots.append(slot)
                slot_supports.append({'slot_label': term, 'supported': True, 'evidence_indices': []})
            else:
                missing_terms.append(term)
                missing_slots.append(slot)
                slot_supports.append({'slot_label': term, 'supported': False, 'evidence_indices': []})

        need_search = bool(missing_terms)
        if need_search:
            reason = 'missing_usable_grounding'
            gap_summary = '현재 질문 핵심 의미 단위 중 usable grounding이 없는 항목이 있어 외부 검색이 필요하다: ' + ', '.join(missing_terms[:4])
        else:
            reason = 'usable_grounding_sufficient'
            gap_summary = '현재 질문 핵심 의미 단위가 이미 grounded 되어 있어 추가 검색 없이 생각 단계로 진행할 수 있다.'

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
                'grounded_terms': grounded_terms,
                'missing_terms': missing_terms,
                'local_only_terms': local_only_terms,
                'term_states': term_states,
                'focus_source': 'meaning_unit_analysis',
            },
        )

    def _collect_keyword_blocks(self, meaning_blocks: list[MeaningBlock]) -> list[MeaningBlock]:
        ranked: list[MeaningBlock] = []
        for block in meaning_blocks:
            if block.block_kind != 'noun_phrase':
                continue
            importance = str(block.metadata.get('importance') or 'secondary').strip()
            search_policy = str(block.metadata.get('search_policy') or 'search_if_unusable').strip()
            if importance == 'ignore' or search_policy == 'ignore':
                continue
            ranked.append(block)
        ranked.sort(key=self._block_sort_key)
        return ranked

    def _block_sort_key(self, block: MeaningBlock) -> tuple[int, int, int]:
        importance = str(block.metadata.get('importance') or 'secondary').strip()
        search_policy = str(block.metadata.get('search_policy') or 'search_if_unusable').strip()
        importance_rank = {'primary': 0, 'secondary': 1, 'background': 2}.get(importance, 3)
        local_rank = 1 if search_policy == 'local_only' else 0
        return (importance_rank, local_rank, block.block_index)

    def _classify_access_state(
        self,
        *,
        node: Node | None,
        current_root_event_id: int | None,
        freshness_kind: str,
        search_policy: str,
    ) -> str:
        if search_policy == 'local_only':
            return 'local_only'
        if node is None:
            return 'node_missing'
        if current_root_event_id is not None and getattr(node, 'created_from_event_id', None) == current_root_event_id:
            return 'mention_only'
        if not self._node_has_grounding(node):
            return 'mention_only'
        if freshness_kind == 'current_state':
            return 'grounded_but_stale'
        return 'grounded_and_usable'

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

    def _slot_dict(self, term: str) -> dict[str, str]:
        return {'kind': 'entity', 'entity': term, 'aspect': '', 'label': term}

    def _norm(self, value: str) -> str:
        return ' '.join(str(value or '').split()).strip().lower()
