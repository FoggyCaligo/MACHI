from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.entities.conclusion import (
    ConflictRecord,
    ContradictionSignal,
    CoreConclusion,
    RevisionAction,
    RevisionDecisionRecord,
    TrustChangeRecord,
)
from core.entities.intent import IntentSnapshot
from core.entities.thought_view import ThoughtView


class ConclusionRequestLike(Protocol):
    session_id: str
    message_id: int | None
    message_text: str


@dataclass(slots=True)
class ConclusionBuilder:
    max_summary_conflicts: int = 3
    max_summary_relations: int = 6

    def build(
        self,
        *,
        request: ConclusionRequestLike,
        thought_view: ThoughtView,
        contradiction_signals: list[ContradictionSignal],
        trust_updates: list[RevisionAction],
        revision_actions: list[RevisionAction],
        intent_snapshot: IntentSnapshot | None = None,
    ) -> CoreConclusion:
        activated_concepts = self._activated_concepts(thought_view)
        if intent_snapshot is None:
            intent_snapshot = self._fallback_intent_snapshot(thought_view=thought_view, contradiction_signals=contradiction_signals, revision_actions=revision_actions)
        key_relations = self._key_relations(thought_view, contradiction_signals, trust_updates, revision_actions)
        detected_conflicts = [self._to_conflict_record(item) for item in contradiction_signals]
        trust_changes = [self._to_trust_change_record(item) for item in trust_updates]
        revision_decisions = [self._to_revision_decision_record(item) for item in revision_actions]
        explanation_summary = self._build_explanation_summary(
            request=request,
            thought_view=thought_view,
            contradiction_signals=contradiction_signals,
            trust_updates=trust_updates,
            revision_actions=revision_actions,
            activated_concepts=activated_concepts,
            key_relations=key_relations,
            intent_snapshot=intent_snapshot,
        )

        return CoreConclusion(
            session_id=request.session_id,
            message_id=request.message_id,
            user_input_summary=self._summarize_user_input(request.message_text),
            inferred_intent=intent_snapshot.snapshot_intent,
            activated_concepts=activated_concepts,
            key_relations=key_relations,
            detected_conflicts=detected_conflicts,
            trust_changes=trust_changes,
            revision_decisions=revision_decisions,
            explanation_summary=explanation_summary,
            metadata={
                'seed_block_count': len(thought_view.seed_blocks),
                'seed_node_count': len(thought_view.seed_nodes),
                'local_node_count': len(thought_view.nodes),
                'local_edge_count': len(thought_view.edges),
                'pointer_count': len(thought_view.pointers),
                'pattern_count': len(thought_view.activated_patterns),
                'intent_basis': 'intent_manager_graph_state',
                'activated_concepts': activated_concepts,
                'intent_snapshot': intent_snapshot.to_metadata(),
            },
        )

    def _activated_concepts(self, thought_view: ThoughtView) -> list[int]:
        seen: set[int] = set()
        ordered: list[int] = []
        for activated in thought_view.seed_nodes:
            node_id = activated.node.id
            if node_id is not None and node_id not in seen:
                ordered.append(node_id)
                seen.add(node_id)
        for node in thought_view.nodes:
            node_id = node.id
            if node_id is not None and node_id not in seen:
                ordered.append(node_id)
                seen.add(node_id)
        return ordered

    def _key_relations(
        self,
        thought_view: ThoughtView,
        contradiction_signals: list[ContradictionSignal],
        trust_updates: list[RevisionAction],
        revision_actions: list[RevisionAction],
    ) -> list[int]:
        ranked: list[int] = []
        seen: set[int] = set()

        def add(edge_id: int | None) -> None:
            if edge_id is None or edge_id in seen:
                return
            seen.add(edge_id)
            ranked.append(edge_id)

        for signal in contradiction_signals:
            add(signal.edge_id)
        for action in trust_updates:
            add(action.edge_id)
        for action in revision_actions:
            add(action.edge_id)
        for edge in sorted(
            thought_view.edges,
            key=lambda item: (
                item.trust_score,
                item.edge_weight,
                item.support_count,
                -item.conflict_count,
            ),
            reverse=True,
        ):
            add(edge.id)
            if len(ranked) >= self.max_summary_relations:
                break
        return ranked

    def _summarize_user_input(self, text: str) -> str:
        compact = ' '.join((text or '').split())
        if len(compact) <= 180:
            return compact
        return compact[:177] + '...'


    def _fallback_intent_snapshot(
        self,
        *,
        thought_view: ThoughtView,
        contradiction_signals: list[ContradictionSignal],
        revision_actions: list[RevisionAction],
    ) -> IntentSnapshot:
        seed_node_count = len(thought_view.seed_nodes)
        edge_count = len(thought_view.edges)
        pointer_count = len(thought_view.pointers)
        pattern_count = len(thought_view.activated_patterns)

        if contradiction_signals or revision_actions:
            intent_name = 'structure_review'
        elif pointer_count and seed_node_count <= 2 and edge_count <= 1:
            intent_name = 'memory_probe'
        elif edge_count == 0 and seed_node_count <= 2:
            intent_name = 'open_information_request'
        elif pattern_count > 0 or edge_count >= max(4, seed_node_count):
            intent_name = 'relation_synthesis_request'
        else:
            intent_name = 'graph_grounded_reasoning'
        return IntentSnapshot(
            drive_name='user_delight',
            live_intent=intent_name,
            snapshot_intent=intent_name,
            sufficiency_score=0.0,
            stop_threshold=0.62,
            should_stop=False,
            evidence=['fallback_graph_state_only'],
            metadata={'fallback': True},
        )

    def _to_conflict_record(self, signal: ContradictionSignal) -> ConflictRecord:
        return ConflictRecord(
            edge_id=signal.edge_id,
            source_node_id=signal.source_node_id,
            target_node_id=signal.target_node_id,
            edge_type=signal.edge_type,
            severity=signal.severity,
            reason=signal.reason,
            score=signal.score,
            metadata=dict(signal.metadata),
        )

    def _to_trust_change_record(self, action: RevisionAction) -> TrustChangeRecord:
        return TrustChangeRecord(
            edge_id=action.edge_id,
            reason=action.reason,
            before_trust=action.before_trust,
            after_trust=action.after_trust,
            before_pressure=action.before_pressure,
            after_pressure=action.after_pressure,
            metadata=dict(action.metadata),
        )

    def _to_revision_decision_record(self, action: RevisionAction) -> RevisionDecisionRecord:
        return RevisionDecisionRecord(
            edge_id=action.edge_id,
            action=action.action,
            reason=action.reason,
            deactivated=action.deactivated,
            before_trust=action.before_trust,
            after_trust=action.after_trust,
            before_pressure=action.before_pressure,
            after_pressure=action.after_pressure,
            metadata=dict(action.metadata),
        )

    def _build_explanation_summary(
        self,
        *,
        request: ConclusionRequestLike,
        thought_view: ThoughtView,
        contradiction_signals: list[ContradictionSignal],
        trust_updates: list[RevisionAction],
        revision_actions: list[RevisionAction],
        activated_concepts: list[int],
        key_relations: list[int],
        intent_snapshot: IntentSnapshot | None = None,
    ) -> str:
        deactivated_count = sum(1 for item in revision_actions if item.deactivated)
        lines = [
            f"입력은 '{self._summarize_user_input(request.message_text)}'로 요약되었고, 현재 사고의 의도 스냅샷은 {intent_snapshot.snapshot_intent}로 정해졌다.",
            f"이번 사고에서는 {len(activated_concepts)}개의 활성 개념 노드와 {len(key_relations)}개의 핵심 관계 참조가 사용되었다.",
            f"구조 점검 결과 충돌 {len(contradiction_signals)}건, 신뢰도 변화 {len(trust_updates)}건, revision 판단 {len(revision_actions)}건이 발생했다.",
        ]
        if intent_snapshot.shifted and intent_snapshot.shift_reason:
            lines.append(f"이전 의도에서 현재 의도로 전환된 이유는 {intent_snapshot.shift_reason} 이다.")
        if contradiction_signals:
            conflict_bits = ', '.join(
                f"edge#{item.edge_id}:{item.reason}" for item in contradiction_signals[: self.max_summary_conflicts]
            )
            lines.append(f"주요 충돌은 {conflict_bits} 이다.")
        if deactivated_count:
            lines.append(f"반복 충돌로 인해 {deactivated_count}개의 엣지가 비활성화되었다.")
        elif revision_actions:
            lines.append('revision 후보를 검토했지만 이번 사이클에서는 구조 보존 쪽이 유지되었다.')
        elif thought_view.edges:
            lines.append('현재 국부 그래프에서는 즉시 구조를 교체할 수준의 변화는 감지되지 않았다.')
        lines.append(
            f"현재 사고의 충분성 평가는 {intent_snapshot.sufficiency_score:.2f} / 임계치 {intent_snapshot.stop_threshold:.2f} 이며, should_stop={intent_snapshot.should_stop} 로 판정되었다."
        )
        return ' '.join(lines)
