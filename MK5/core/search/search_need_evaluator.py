from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.cognition.input_segmenter import InputSegmenter
from core.cognition.hash_resolver import HashResolver
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
    grounding_scope_limit: int = 8
    hash_resolver: HashResolver = field(default_factory=HashResolver)
    segmenter: InputSegmenter = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, 'segmenter', InputSegmenter(hash_resolver=self.hash_resolver))

    def evaluate(
        self,
        *,
        message: str,
        thought_view: ThoughtView,
        conclusion: CoreConclusion,
    ) -> SearchNeedDecision:
        current_root_event_id = thought_view.metadata.get('current_root_event_id') if isinstance(thought_view.metadata, dict) else None
        scope_nodes = self._grounding_scope_nodes(thought_view, current_root_event_id=current_root_event_id)
        target_terms, focus_terms = self._extract_target_terms(message=message, thought_view=thought_view)
        target_node_ids = [node.id for node in scope_nodes if node.id is not None]

        grounded_terms: list[str] = []
        missing_terms: list[str] = []
        grounded_focus_terms: list[str] = []
        missing_focus_terms: list[str] = []
        slot_supports: list[dict[str, Any]] = []
        for term in target_terms:
            supported = self._has_entity_grounding(scope_nodes, term)
            if supported:
                grounded_terms.append(term)
                if term in focus_terms:
                    grounded_focus_terms.append(term)
            else:
                missing_terms.append(term)
                if term in focus_terms:
                    missing_focus_terms.append(term)
            slot_supports.append({
                'slot_label': term,
                'supported': supported,
                'evidence_indices': [],
            })

        need_search = bool(missing_focus_terms)
        reason = 'missing_concept_grounding' if need_search else 'concept_grounding_sufficient'
        if need_search:
            gap_summary = '현재 질문 핵심 개념 중 아직 grounding이 없는 항목이 있어 외부 검색이 필요하다: ' + ', '.join(missing_focus_terms[:6])
        else:
            gap_summary = '현재 질문에서 접근된 개념이 기존 그래프 안에서 이미 grounding되어 있어 외부 검색 없이 진행할 수 있다.'

        return SearchNeedDecision(
            need_search=need_search,
            reason=reason,
            gap_summary=gap_summary,
            target_node_ids=target_node_ids,
            target_terms=target_terms,
            requested_slots=[{'kind': 'concept', 'entity': term, 'aspect': '', 'label': term} for term in target_terms],
            covered_slots=[{'kind': 'concept', 'entity': term, 'aspect': '', 'label': term} for term in grounded_terms],
            missing_slots=[{'kind': 'concept', 'entity': term, 'aspect': '', 'label': term} for term in missing_terms],
            slot_supports=slot_supports,
            metadata={
                'grounding_scope_node_ids': target_node_ids,
                'grounded_terms': grounded_terms,
                'missing_terms': missing_terms,
                'focus_terms': focus_terms,
                'grounded_focus_terms': grounded_focus_terms,
                'missing_focus_terms': missing_focus_terms,
                'current_root_event_id': current_root_event_id,
                'targeting_mode': 'concept_access_only',
            },
        )

    def _extract_target_terms(self, *, message: str, thought_view: ThoughtView) -> tuple[list[str], list[str]]:
        sentence_to_terms: dict[int, list[str]] = {}
        blocks = list(thought_view.seed_blocks or [])
        if not blocks:
            blocks = self.segmenter.segment(message)
        for block in blocks:
            if getattr(block, 'block_kind', '') != 'noun_phrase':
                continue
            term = self._norm(getattr(block, 'normalized_text', '') or getattr(block, 'text', ''))
            if not term:
                continue
            sentence_index = getattr(block, 'sentence_index', 0)
            sentence_to_terms.setdefault(sentence_index, [])
            if term not in sentence_to_terms[sentence_index]:
                sentence_to_terms[sentence_index].append(term)
        if not sentence_to_terms:
            return [], []
        ordered_sentences = sorted(sentence_to_terms.items(), key=lambda item: (-len(item[1]), item[0]))
        focus_sentence_terms = ordered_sentences[0][1]
        focus_terms = focus_sentence_terms[:2]
        terms: list[str] = []
        for _, items in ordered_sentences:
            for term in items:
                if term not in terms:
                    terms.append(term)
        return terms, focus_terms

    def _grounding_scope_nodes(self, thought_view: ThoughtView, *, current_root_event_id: int | None) -> list[Node]:
        scope: list[Node] = []
        seen_ids: set[int] = set()
        for node in list(thought_view.nodes or []) + [item.node for item in list(thought_view.seed_nodes or [])]:
            if node.id is None or node.id in seen_ids:
                continue
            if current_root_event_id is not None and node.created_from_event_id == current_root_event_id:
                continue
            scope.append(node)
            seen_ids.add(node.id)
            if len(scope) >= self.grounding_scope_limit + max(2, len(thought_view.seed_nodes or [])):
                break
        return scope

    def _has_entity_grounding(self, nodes: list[Node], entity: str) -> bool:
        term = self._norm(entity)
        if not term:
            return False
        for node in nodes:
            if not self._node_has_grounding(node):
                continue
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
        passages = payload.get('passages') or []
        if isinstance(passages, list):
            parts.extend(str(item or '') for item in passages)
        aliases = payload.get('raw_aliases') or []
        if isinstance(aliases, list):
            parts.extend(str(item or '') for item in aliases)
        return self._norm(' '.join(parts))

    def _norm(self, value: str) -> str:
        return ' '.join(str(value or '').split()).strip().lower()
