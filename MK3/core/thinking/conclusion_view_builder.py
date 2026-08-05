from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from core.entities.conclusion import ThoughtResult
from core.entities.conclusion_view import ConclusionView
from core.entities.edge import Edge
from core.entities.node import Node
from core.entities.thought_view import ThoughtView

_NODE_TRUST_THRESHOLD = 0.3
_EDGE_TRUST_THRESHOLD = 0.3


class ConclusionViewRequestLike(Protocol):
    session_id: str
    message_id: int | None
    message_text: str


@dataclass(slots=True)
class ConclusionViewBuilder:
    """Think→Search 루프 종료 후 최종 ThoughtView/ThoughtResult를 받아
    의도 키워드 기반 룰로 ConclusionView를 구성하는 서비스.

    선별 규칙:
    - 노드: is_active=True + trust_score >= threshold
            + 키워드 매칭 또는 1-hop 이웃 (키워드 없으면 seed_nodes 전체)
    - 엣지: 선별된 노드 간 + connect_type != 'conflict' + trust_score >= threshold
    - 순서: trust_score 내림차순 → logical_sequence
    """

    node_trust_threshold: float = _NODE_TRUST_THRESHOLD
    edge_trust_threshold: float = _EDGE_TRUST_THRESHOLD

    def build(
        self,
        *,
        request: ConclusionViewRequestLike,
        thought_view: ThoughtView,
        thought_result: ThoughtResult,
    ) -> ConclusionView:
        intent_keywords = self._extract_intent_keywords(thought_result)
        inferred_intent = self._extract_inferred_intent(thought_result)

        intent_aligned_nodes, contradicted_nodes = self._select_nodes(thought_view, intent_keywords)
        aligned_node_ids = {n.id for n in intent_aligned_nodes if n.id is not None}
        supporting_edges = self._select_edges(thought_view, aligned_node_ids)

        logical_sequence = [n.id for n in intent_aligned_nodes if n.id is not None]
        confidence = self._compute_confidence(intent_aligned_nodes)

        explanation_summary = self._build_explanation_summary(
            request=request,
            intent_keywords=intent_keywords,
            intent_aligned_nodes=intent_aligned_nodes,
            thought_result=thought_result,
        )

        core = thought_result.core_conclusion
        metadata = dict(core.metadata) if core and isinstance(core.metadata, dict) else {}

        return ConclusionView(
            session_id=request.session_id,
            message_id=request.message_id,
            user_input_summary=self._summarize_user_input(request.message_text),
            intent_keywords=intent_keywords,
            inferred_intent=inferred_intent,
            intent_aligned_nodes=intent_aligned_nodes,
            supporting_edges=supporting_edges,
            contradicted_nodes=contradicted_nodes,
            logical_sequence=logical_sequence,
            confidence=confidence,
            activated_concepts=[n.id for n in intent_aligned_nodes if n.id is not None],
            key_relations=[e.id for e in supporting_edges if e.id is not None],
            explanation_summary=explanation_summary,
            detected_conflicts=list(core.detected_conflicts) if core else [],
            trust_changes=list(core.trust_changes) if core else [],
            revision_decisions=list(core.revision_decisions) if core else [],
            metadata=metadata,
        )

    # ── 의도 키워드 추출 ─────────────────────────────────────────────────────

    def _extract_intent_keywords(self, thought_result: ThoughtResult) -> list[str]:
        core = thought_result.core_conclusion
        if core and isinstance(core.metadata, dict):
            terms = core.metadata.get('topic_terms') or []
            return [str(t).strip() for t in terms if str(t).strip()]
        return []

    def _extract_inferred_intent(self, thought_result: ThoughtResult) -> str:
        core = thought_result.core_conclusion
        return core.inferred_intent if core else 'graph_grounded_reasoning'

    # ── 노드 선별 ────────────────────────────────────────────────────────────

    def _select_nodes(
        self,
        thought_view: ThoughtView,
        keywords: list[str],
    ) -> tuple[list[Node], list[Node]]:
        keywords_lower = [k.lower() for k in keywords if k]

        # 1단계: 키워드 매칭 노드 ID 수집 (nodes + seed_nodes)
        keyword_matched_ids: set[int] = set()
        for node in thought_view.nodes:
            if self._node_is_eligible(node) and self._node_matches_keywords(node, keywords_lower):
                if node.id is not None:
                    keyword_matched_ids.add(node.id)
        for activated in thought_view.seed_nodes:
            node = activated.node
            if self._node_is_eligible(node) and self._node_matches_keywords(node, keywords_lower):
                if node.id is not None:
                    keyword_matched_ids.add(node.id)

        # 키워드 매칭 없으면 seed_nodes 전체를 후보로
        if not keyword_matched_ids:
            for activated in thought_view.seed_nodes:
                node = activated.node
                if self._node_is_eligible(node) and node.id is not None:
                    keyword_matched_ids.add(node.id)

        aligned: list[Node] = []
        contradicted: list[Node] = []
        seen: set[int] = set()

        for node in thought_view.nodes:
            if node.id is None or node.id in seen:
                continue
            if not node.is_active:
                continue
            seen.add(node.id)

            if node.trust_score < self.node_trust_threshold:
                contradicted.append(node)
                continue

            if node.id in keyword_matched_ids:
                aligned.append(node)
            elif self._is_neighbor_of(node.id, keyword_matched_ids, thought_view):
                aligned.append(node)

        aligned.sort(key=lambda n: n.trust_score, reverse=True)
        return aligned, contradicted

    def _node_is_eligible(self, node: Node) -> bool:
        return bool(node.is_active and node.trust_score >= self.node_trust_threshold)

    def _node_matches_keywords(self, node: Node, keywords_lower: list[str]) -> bool:
        if not keywords_lower:
            return True
        label = (
            getattr(node, 'normalized_value', '') or
            getattr(node, 'raw_value', '') or ''
        ).lower().strip()
        if not label:
            return False
        return any(kw in label or label in kw for kw in keywords_lower)

    def _is_neighbor_of(
        self,
        node_id: int,
        target_ids: set[int],
        thought_view: ThoughtView,
    ) -> bool:
        for edge in thought_view.edges:
            src = getattr(edge, 'source_node_id', None)
            tgt = getattr(edge, 'target_node_id', None)
            if (src in target_ids and tgt == node_id) or (tgt in target_ids and src == node_id):
                return True
        return False

    # ── 엣지 선별 ────────────────────────────────────────────────────────────

    def _select_edges(self, thought_view: ThoughtView, aligned_node_ids: set[int]) -> list[Edge]:
        selected: list[Edge] = []
        for edge in thought_view.edges:
            src = getattr(edge, 'source_node_id', None)
            tgt = getattr(edge, 'target_node_id', None)
            if src not in aligned_node_ids or tgt not in aligned_node_ids:
                continue
            if getattr(edge, 'connect_type', '') == 'conflict':
                continue
            if edge.trust_score < self.edge_trust_threshold:
                continue
            selected.append(edge)
        selected.sort(key=lambda e: e.trust_score, reverse=True)
        return selected

    # ── 신뢰도 계산 ──────────────────────────────────────────────────────────

    def _compute_confidence(self, nodes: list[Node]) -> float:
        if not nodes:
            return 0.0
        return sum(n.trust_score for n in nodes) / len(nodes)

    # ── 설명 요약 (룰 기반) ──────────────────────────────────────────────────

    def _build_explanation_summary(
        self,
        *,
        request: ConclusionViewRequestLike,
        intent_keywords: list[str],
        intent_aligned_nodes: list[Node],
        thought_result: ThoughtResult,
    ) -> str:
        topic = self._summarize_user_input(request.message_text)
        has_conflicts = bool(thought_result.contradiction_signals)
        has_revisions = bool(thought_result.revision_actions)
        has_context = bool(intent_aligned_nodes)

        if has_conflicts:
            summary = (
                f"'{topic}'에 대해 바로 단정하기엔 아직 내부 판단 충돌이 남아 있어, "
                '지금은 보수적으로 답하는 편이 맞다.'
            )
        elif has_revisions:
            summary = (
                f"'{topic}'와 관련한 기존 이해를 다시 점검하는 흐름이 있어, "
                '확실한 부분만 짚는 편이 맞다.'
            )
        elif has_context:
            kw_label = ' / '.join(intent_keywords[:3]) if intent_keywords else topic
            summary = (
                f"'{kw_label}' 관련 맥락이 그래프에서 확인되어, "
                '현재 확보된 범위 안에서 답을 정리할 수 있다.'
            )
        else:
            summary = (
                f"'{topic}'를 다루기 위한 맥락이 아직 충분하지 않아, "
                '가능한 범위만 조심스럽게 말하는 편이 맞다.'
            )

        # intent_snapshot 기반 보조 문장
        core = thought_result.core_conclusion
        if core and isinstance(core.metadata, dict):
            snap: dict[str, Any] = dict(core.metadata.get('intent_snapshot') or {})
            topic_continuity = str(snap.get('topic_continuity') or '')
            should_stop = bool(snap.get('should_stop'))
            snapshot_intent = str(snap.get('snapshot_intent') or '')

            if not has_conflicts and not has_revisions:
                if topic_continuity == 'continued_topic':
                    summary += ' 이전 턴과 같은 주제를 이어서 보고 있다.'
                elif topic_continuity == 'related_topic':
                    summary += ' 이전 주제와 일부 이어지지만 초점은 조금 달라졌다.'
                elif topic_continuity == 'shifted_topic':
                    summary += ' 이전 턴과는 다른 주제로 넘어간 상태다.'

            if should_stop and has_context and not has_conflicts and not has_revisions:
                summary += ' 지금은 더 크게 억지 해석을 덧붙이지 않는 편이 낫다.'

            if snapshot_intent == 'memory_probe':
                recent_count = int(core.metadata.get('recent_memory_count') or 0)
                if recent_count > 0:
                    summary += f' 최근 {recent_count}턴의 세션 메모리가 활성화되어 있다.'
                else:
                    summary += ' 이번 턴에는 세션 메모리가 활성화되지 않았다.'

        return summary

    def _summarize_user_input(self, text: str) -> str:
        compact = ' '.join((text or '').split())
        if len(compact) <= 180:
            return compact
        return compact[:177] + '...'
