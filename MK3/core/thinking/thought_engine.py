from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from core.entities.conclusion import ThoughtResult
from core.entities.graph_event import GraphEvent
from core.entities.thought_view import ThoughtView
from core.thinking.concept_differentiation_service import ConceptDifferentiationService
from core.thinking.conclusion_builder import ConclusionBuilder
from core.thinking.contradiction_detector import ContradictionDetector
from core.thinking.intent_manager import IntentManager
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
        concept_differentiation_service: ConceptDifferentiationService | None = None,
        conclusion_builder: ConclusionBuilder | None = None,
        intent_manager: IntentManager | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.contradiction_detector = contradiction_detector or ContradictionDetector()
        self.trust_manager = trust_manager or TrustManager()
        self.structure_revision_service = structure_revision_service or StructureRevisionService(
            node_merge_service=NodeMergeService(uow_factory),
        )
        self.concept_differentiation_service = (
            concept_differentiation_service or ConceptDifferentiationService()
        )
        self.conclusion_builder = conclusion_builder or ConclusionBuilder()
        self.intent_manager = intent_manager or IntentManager()

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
            # 개념 분화: trust/revision 이후, intent 결정 이전
            # partial_reuse 누적 → concept/flow, 공유 이웃 → concept/neutral
            # 고강도 contradiction signal → concept/conflict
            differentiation_result = self.concept_differentiation_service.differentiate(
                uow,
                thought_view=thought_view,
                message_id=request.message_id,
                contradiction_signals=signals,
            )
            intent_snapshot = self.intent_manager.resolve(
                uow,
                request=request,
                thought_view=thought_view,
                contradiction_signals=signals,
                trust_updates=trust_updates,
                revision_actions=revision_actions,
            )
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
                'differentiation': differentiation_result.to_metadata(),
                'intent_snapshot': intent_snapshot.to_metadata(),
            },
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
