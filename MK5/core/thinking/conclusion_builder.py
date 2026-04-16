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


class MissingIntentSnapshotError(RuntimeError):
    """Raised when conclusion building is attempted without a resolved intent snapshot."""


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
            raise MissingIntentSnapshotError(
                'ConclusionBuilder.build() requires an intent_snapshot from IntentManager. '
                'Do not fall back to inferred graph-state intent here.'
            )
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
                'topic_terms': list(intent_snapshot.topic_terms),
                'previous_topic_terms': list(intent_snapshot.previous_topic_terms),
                'topic_continuity': intent_snapshot.topic_continuity,
                'previous_tone_hint': intent_snapshot.previous_tone_hint,
                'recent_memory_messages': list((thought_view.metadata or {}).get('recent_memory_messages') or []),
                'recent_memory_count': int((thought_view.metadata or {}).get('recent_memory_count') or 0),
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

    def _to_conflict_record(self, signal: ContradictionSignal) -> ConflictRecord:
        return ConflictRecord(
            edge_id=signal.edge_id,
            source_node_id=signal.source_node_id,
            target_node_id=signal.target_node_id,
            edge_label=signal.edge_label,
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
        topic = self._summarize_user_input(request.message_text)
        has_context = bool(activated_concepts or key_relations)
        has_uncertainty = bool(contradiction_signals or revision_actions or trust_updates)

        if contradiction_signals:
            summary = (
                f"'{topic}'에 대해 바로 단정하기엔 아직 내부 판단 충돌이 남아 있어, "
                '지금은 보수적으로 답하는 편이 맞다.'
            )
        elif revision_actions:
            summary = (
                f"'{topic}'와 관련한 기존 이해를 다시 점검하는 흐름이 있어, "
                '확실한 부분만 짚는 편이 맞다.'
            )
        elif has_context:
            summary = (
                f"'{topic}'와 이어지는 기존 맥락이 일부 있어, "
                '현재 확보된 범위 안에서 답을 정리할 수 있다.'
            )
        else:
            summary = (
                f"'{topic}'를 다루기 위한 맥락이 아직 충분하지 않아, "
                '가능한 범위만 조심스럽게 말하는 편이 맞다.'
            )

        if intent_snapshot and intent_snapshot.shifted and intent_snapshot.shift_reason and not has_uncertainty:
            summary += ' 이전 흐름과는 조금 다른 주제로 옮겨간 상태다.'
        if intent_snapshot and intent_snapshot.topic_continuity == 'continued_topic' and not has_uncertainty:
            summary += ' 이전 턴과 같은 주제를 이어서 보고 있다.'
        elif intent_snapshot and intent_snapshot.topic_continuity == 'related_topic' and not has_uncertainty:
            summary += ' 이전 주제와 일부 이어지지만 초점은 조금 달라졌다.'
        elif intent_snapshot and intent_snapshot.topic_continuity == 'shifted_topic' and not has_uncertainty:
            summary += ' 이전 턴과는 다른 주제로 넘어간 상태다.'

        if intent_snapshot and intent_snapshot.should_stop and has_context and not has_uncertainty:
            summary += ' 지금은 더 크게 억지 해석을 덧붙이지 않는 편이 낫다.'

        recent_memory_count = int((thought_view.metadata or {}).get('recent_memory_count') or 0)
        if intent_snapshot and intent_snapshot.snapshot_intent == 'memory_probe':
            if recent_memory_count > 0:
                summary += f' Recent session memory is available from {recent_memory_count} recent conversation turns.'
            else:
                summary += ' No recent session memory was activated for this turn.'

        return summary
