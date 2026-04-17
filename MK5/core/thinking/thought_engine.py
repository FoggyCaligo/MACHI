from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from core.entities.conclusion import ThoughtResult
from core.entities.graph_event import GraphEvent
from core.entities.intent import IntentSnapshot
from core.entities.thought_view import ThoughtView
from core.thinking.conclusion_builder import ConclusionBuilder
from core.thinking.contradiction_detector import ContradictionDetector
from core.thinking.structure_revision_service import StructureRevisionService
from core.thinking.trust_manager import TrustManager
from core.update.node_merge_service import NodeMergeService
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class ThoughtRequest:
    session_id: str
    message_id: int | None = None
    message_text: str = ''


class ThoughtEngine:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        contradiction_detector: ContradictionDetector | None = None,
        trust_manager: TrustManager | None = None,
        structure_revision_service: StructureRevisionService | None = None,
        conclusion_builder: ConclusionBuilder | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.contradiction_detector = contradiction_detector or ContradictionDetector()
        self.trust_manager = trust_manager or TrustManager()
        self.structure_revision_service = structure_revision_service or StructureRevisionService(
            node_merge_service=NodeMergeService(uow_factory),
        )
        self.conclusion_builder = conclusion_builder or ConclusionBuilder()

    def think(self, request: ThoughtRequest, thought_view: ThoughtView) -> ThoughtResult:
        with self.uow_factory() as uow:
            signals = self.contradiction_detector.inspect(thought_view)
            trust_updates = [
                action
                for signal in signals
                if (action := self.trust_manager.apply_signal(uow, signal, message_id=request.message_id)) is not None
            ]
            revision_actions = self.structure_revision_service.review_candidates(
                uow,
                message_id=request.message_id,
            )
            intent_snapshot = self._build_minimal_intent_snapshot(thought_view)
            uow.commit()

        core_conclusion = self.conclusion_builder.build(
            request=request,
            thought_view=thought_view,
            contradiction_signals=signals,
            trust_updates=trust_updates,
            revision_actions=revision_actions,
            intent_snapshot=intent_snapshot,
        )

        return ThoughtResult(
            session_id=request.session_id,
            message_id=request.message_id,
            contradiction_signals=signals,
            trust_updates=trust_updates,
            revision_actions=revision_actions,
            core_conclusion=core_conclusion,
            summary=core_conclusion.explanation_summary,
            metadata={
                'seed_node_count': len(thought_view.seed_nodes),
                'local_node_count': len(thought_view.nodes),
                'local_edge_count': len(thought_view.edges),
                'signal_count': len(signals),
                'trust_update_count': len(trust_updates),
                'revision_action_count': len(revision_actions),
                'differentiation': {'enabled': False, 'reason': 'slimmed_runtime_disabled'},
                'intent_snapshot': intent_snapshot.to_metadata(),
            },
        )


    def _build_minimal_intent_snapshot(self, thought_view: ThoughtView) -> IntentSnapshot:
        metadata = thought_view.metadata or {}
        current_topic_terms = list(metadata.get('current_topic_terms') or [])
        previous_topic_terms = list(metadata.get('previous_topic_terms') or [])
        overlap = len(set(current_topic_terms).intersection(previous_topic_terms))
        if overlap > 0:
            continuity = 'continued_topic'
        elif previous_topic_terms:
            continuity = 'shifted_topic'
        else:
            continuity = 'unknown'
        return IntentSnapshot(
            snapshot_intent='graph_grounded_reasoning',
            topic_terms=current_topic_terms[:6],
            previous_topic_terms=previous_topic_terms[:6],
            topic_continuity=continuity,
            topic_overlap_count=overlap,
            previous_tone_hint=str(metadata.get('previous_tone_hint') or ''),
            metadata={'intent_manager_enabled': False, 'source': 'minimal_intent_snapshot'},
        )

    def run_revision_review(
        self,
        *,
        message_id: int | None = None,
        limit: int = 100,
        trigger: str = 'system_internal',
    ) -> list:
        with self.uow_factory() as uow:
            actions = self.structure_revision_service.review_candidates(
                uow,
                message_id=message_id,
                limit=limit,
            )
            uow.graph_events.add(
                GraphEvent(
                    event_uid=f'evt_{uuid4().hex}',
                    event_type='revision_review_cycle',
                    message_id=message_id,
                    parsed_input={
                        'trigger': trigger,
                        'limit': limit,
                    },
                    effect={
                        'action_count': len(actions),
                        'actions': [item.action for item in actions],
                    },
                    note='Independent revision review cycle executed.',
                )
            )
            uow.commit()
        return actions
