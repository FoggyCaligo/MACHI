from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.entities.conclusion import ThoughtResult
from core.entities.thought_view import ThoughtView
from core.thinking.conclusion_builder import ConclusionBuilder
from core.thinking.contradiction_detector import ContradictionDetector
from core.thinking.structure_revision_service import StructureRevisionService
from core.thinking.trust_manager import TrustManager
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
        self.structure_revision_service = structure_revision_service or StructureRevisionService()
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
            uow.commit()

        core_conclusion = self.conclusion_builder.build(
            request=request,
            thought_view=thought_view,
            contradiction_signals=signals,
            trust_updates=trust_updates,
            revision_actions=revision_actions,
        )
        summary = core_conclusion.explanation_summary

        return ThoughtResult(
            session_id=request.session_id,
            message_id=request.message_id,
            contradiction_signals=signals,
            trust_updates=trust_updates,
            revision_actions=revision_actions,
            core_conclusion=core_conclusion,
            summary=summary,
            metadata={
                'seed_node_count': len(thought_view.seed_nodes),
                'local_node_count': len(thought_view.nodes),
                'local_edge_count': len(thought_view.edges),
                'signal_count': len(signals),
                'trust_update_count': len(trust_updates),
                'revision_action_count': len(revision_actions),
            },
        )
