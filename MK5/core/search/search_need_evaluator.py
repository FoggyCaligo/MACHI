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
    sparse_concept_threshold: int = 3
    sparse_relation_threshold: int = 2
    multi_topic_threshold: int = 2
    grounding_scope_limit: int = 6

    def evaluate(self, *, message: str, thought_view: ThoughtView, conclusion: CoreConclusion) -> SearchNeedDecision:
        explicit_memory_probe = conclusion.inferred_intent == 'memory_probe'
        open_request = conclusion.inferred_intent in {'open_information_request', 'relation_synthesis_request'}
        graph_reasoning = conclusion.inferred_intent == 'graph_grounded_reasoning'
        unresolved_conflict = bool(conclusion.detected_conflicts)

        activated_node_ids = [node.id for node in thought_view.nodes if node.id is not None]
        seed_node_ids = [item.node.id for item in thought_view.seed_nodes if item.node.id is not None]
        scope_nodes = self._grounding_scope_nodes(thought_view)
        target_terms = self._collect_target_terms(thought_view, scope_nodes=scope_nodes)
        sparse_graph = (
            len(conclusion.activated_concepts) <= self.sparse_concept_threshold
            or len(conclusion.key_relations) <= self.sparse_relation_threshold
        )
        multi_topic_request = len(target_terms) >= self.multi_topic_threshold
        has_search_grounding = self._has_search_grounding(scope_nodes)
        internal_world_support = self._has_internal_world_support(scope_nodes)
        no_external_grounding = not has_search_grounding

        need_search = False
        if explicit_memory_probe:
            reason = 'memory_probe_no_external_search'
            gap_summary = '기억 여부를 묻는 질문이라 외부 검색보다 현재 세션 상태를 직접 답하는 편이 맞다.'
        elif unresolved_conflict and no_external_grounding:
            need_search = True
            reason = 'graph_conflict_requires_grounding'
            gap_summary = '현재 사고 그래프에 충돌이 남아 있어 현재 주제를 외부 근거로 다시 확인할 필요가 있다.'
        elif graph_reasoning and multi_topic_request and no_external_grounding and (sparse_graph or not internal_world_support):
            need_search = True
            reason = 'graph_reasoning_needs_external_grounding'
            gap_summary = '여러 개념을 비교·정리하려면 현재 그래프만으로는 부족해 외부 근거를 먼저 확인하는 편이 맞다.'
        elif open_request and no_external_grounding and (sparse_graph or multi_topic_request) and not internal_world_support:
            need_search = True
            reason = 'open_request_without_external_grounding'
            gap_summary = '현재 주제는 설명이나 비교가 필요한데, 관련 핵심 노드에 외부 근거가 아직 직접 연결되어 있지 않다.'
        elif sparse_graph and no_external_grounding and not internal_world_support:
            need_search = True
            reason = 'graph_too_sparse_for_answer'
            gap_summary = '현재 활성화된 개념과 관계만으로는 질문에 답할 근거가 충분하지 않다.'
        else:
            reason = 'graph_sufficient_without_search'
            gap_summary = '현재 활성화된 관련 개념과 관계만으로도 질문에 직접 답할 수 있다.'

        return SearchNeedDecision(
            need_search=need_search,
            reason=reason,
            gap_summary=gap_summary,
            target_node_ids=[node.id for node in scope_nodes if node.id is not None] or seed_node_ids or activated_node_ids,
            target_terms=target_terms,
            metadata={
                'sparse_graph': sparse_graph,
                'unresolved_conflict': unresolved_conflict,
                'open_request': open_request,
                'graph_reasoning': graph_reasoning,
                'multi_topic_request': multi_topic_request,
                'has_search_grounding': has_search_grounding,
                'has_internal_world_support': internal_world_support,
                'activated_node_count': len(activated_node_ids),
                'seed_node_count': len(seed_node_ids),
                'grounding_scope_node_ids': [node.id for node in scope_nodes if node.id is not None],
            },
        )

    def _grounding_scope_nodes(self, thought_view: ThoughtView) -> list[Node]:
        scope: list[Node] = []
        seen_ids: set[int] = set()
        for activated in thought_view.seed_nodes:
            node = activated.node
            if node.id is None or node.id in seen_ids:
                continue
            scope.append(node)
            seen_ids.add(node.id)
            if len(scope) >= self.grounding_scope_limit:
                return scope
        for node in thought_view.nodes:
            if node.id is None or node.id in seen_ids:
                continue
            scope.append(node)
            seen_ids.add(node.id)
            if len(scope) >= self.grounding_scope_limit:
                break
        return scope

    def _has_search_grounding(self, nodes: list[Node]) -> bool:
        for node in nodes:
            payload = node.payload if isinstance(node.payload, dict) else {}
            if payload.get('source_type') == 'search' or payload.get('claim_domain') == 'world_fact':
                return True
        return False

    def _has_internal_world_support(self, nodes: list[Node]) -> bool:
        for node in nodes:
            payload = node.payload if isinstance(node.payload, dict) else {}
            if payload.get('source_type') == 'assistant':
                continue
            if node.trust_score >= 0.7 and node.stability_score >= 0.6:
                return True
        return False

    def _collect_target_terms(self, thought_view: ThoughtView, *, scope_nodes: list[Node]) -> list[str]:
        terms: list[str] = []
        for node in scope_nodes:
            self._append_term(terms, node.normalized_value)
            payload = node.payload if isinstance(node.payload, dict) else {}
            aliases = payload.get('raw_aliases', [])
            if isinstance(aliases, list):
                for alias in aliases:
                    self._append_term(terms, alias)
            if not node.normalized_value:
                self._append_term(terms, node.raw_value)
        return terms[:6]

    def _append_term(self, terms: list[str], value: object) -> None:
        token = ' '.join(str(value or '').split()).strip()
        if not token or len(token) < 2 or len(token) > 80:
            return
        if token in terms:
            return
        terms.append(token)
