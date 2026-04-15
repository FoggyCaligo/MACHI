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
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchNeedEvaluator:
    def evaluate(self, *, message: str, thought_view: ThoughtView, conclusion: CoreConclusion) -> SearchNeedDecision:
        explicit_memory_probe = conclusion.inferred_intent == 'memory_probe'
        unresolved_conflict = bool(conclusion.detected_conflicts)
        open_request = conclusion.inferred_intent in {'open_information_request', 'relation_synthesis_request'}
        reasoning_request = conclusion.inferred_intent == 'graph_grounded_reasoning'
        target_nodes = self._target_nodes(thought_view)
        target_node_ids = [node.id for node in target_nodes if node.id is not None]
        target_terms = self._collect_target_terms(target_nodes)
        target_grounded = self._has_search_grounding(target_nodes)
        sparse_target_graph = len(target_node_ids) <= 2 and len(conclusion.key_relations) <= 1
        multi_term_topic = len(target_terms) >= 2

        need_search = False
        reason = 'graph_sufficient_without_search'
        gap_summary = '현재 활성화된 주제 범위 안에서 바로 답할 수 있다.'

        if explicit_memory_probe:
            reason = 'memory_probe_no_external_search'
            gap_summary = '기억 여부를 묻는 요청이라 외부 검색보다 현재 세션 상태를 직접 답하는 편이 맞다.'
        elif unresolved_conflict and not target_grounded:
            need_search = True
            reason = 'graph_conflict_requires_grounding'
            gap_summary = '현재 주제와 직접 연결된 외부 근거가 없어, 남아 있는 충돌을 확인하기 위해 검색이 필요하다.'
        elif open_request and not target_grounded:
            need_search = True
            reason = 'open_request_without_external_grounding'
            gap_summary = '현재 주제는 설명이나 비교가 필요한데, 현재 관련 주제 범위 안에 외부 근거가 아직 직접 연결되어 있지 않다.'
        elif reasoning_request and multi_term_topic and sparse_target_graph and not target_grounded:
            need_search = True
            reason = 'graph_reasoning_needs_external_grounding'
            gap_summary = '현재 관련 주제들의 활성 구조만으로는 비교·정리를 닫기 어려워, 외부 근거를 먼저 확보하는 편이 맞다.'
        elif sparse_target_graph and not target_grounded and target_terms:
            need_search = True
            reason = 'graph_too_sparse_for_answer'
            gap_summary = '현재 질문과 직접 연결된 활성 노드와 관계만으로는 답을 닫을 근거가 충분하지 않다.'

        return SearchNeedDecision(
            need_search=need_search,
            reason=reason,
            gap_summary=gap_summary,
            target_node_ids=target_node_ids,
            target_terms=target_terms,
            metadata={
                'unresolved_conflict': unresolved_conflict,
                'open_request': open_request,
                'reasoning_request': reasoning_request,
                'target_grounded': target_grounded,
                'sparse_target_graph': sparse_target_graph,
                'target_node_count': len(target_node_ids),
            },
        )

    def _target_nodes(self, thought_view: ThoughtView) -> list[Node]:
        ordered: list[Node] = []
        seen: set[int] = set()
        for activated in thought_view.seed_nodes:
            node = activated.node
            node_id = node.id
            if node_id is not None and node_id in seen:
                continue
            if node_id is not None:
                seen.add(node_id)
            ordered.append(node)
        if ordered:
            return ordered[:6]
        for node in thought_view.nodes:
            node_id = node.id
            if node_id is not None and node_id in seen:
                continue
            if node_id is not None:
                seen.add(node_id)
            ordered.append(node)
            if len(ordered) >= 6:
                break
        return ordered

    def _has_search_grounding(self, nodes: list[Node]) -> bool:
        for node in nodes:
            payload = node.payload if isinstance(node.payload, dict) else {}
            if payload.get('source_type') == 'search' or payload.get('claim_domain') == 'world_fact':
                return True
        return False

    def _collect_target_terms(self, nodes: list[Node]) -> list[str]:
        terms: list[str] = []
        for node in nodes:
            for candidate in (node.normalized_value, node.raw_value):
                self._append_term(terms, candidate)
            aliases = (node.payload or {}).get('raw_aliases', []) if isinstance(node.payload, dict) else []
            if isinstance(aliases, list):
                for alias in aliases:
                    self._append_term(terms, alias)
        return terms[:6]

    def _append_term(self, terms: list[str], value: object) -> None:
        token = str(value or '').strip()
        if not token or len(token) < 2 or len(token) > 80:
            return
        if token in terms:
            return
        terms.append(token)
