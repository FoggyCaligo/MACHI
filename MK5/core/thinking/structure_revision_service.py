from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from core.entities.conclusion import RevisionAction
from core.entities.graph_event import GraphEvent
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class StructureRevisionService:
    min_candidate_pressure: float = 3.0
    deactivate_trust_threshold: float = 0.2
    deactivate_pressure_threshold: float = 4.0
    deactivate_conflict_threshold: int = 4

    def review_candidates(
        self,
        uow: UnitOfWork,
        *,
        message_id: int | None = None,
        limit: int = 100,
    ) -> list[RevisionAction]:
        actions: list[RevisionAction] = []
        for edge in uow.edges.list_revision_candidates(
            min_contradiction_pressure=self.min_candidate_pressure,
            limit=limit,
        ):
            action = self._review_one(uow, edge.id or 0, message_id=message_id)
            if action is not None:
                actions.append(action)
        return actions

    def _review_one(
        self,
        uow: UnitOfWork,
        edge_id: int,
        *,
        message_id: int | None = None,
    ) -> RevisionAction | None:
        edge = uow.edges.get_by_id(edge_id)
        if edge is None or not edge.is_active:
            return None

        should_deactivate = (
            edge.trust_score <= self.deactivate_trust_threshold
            or edge.contradiction_pressure >= self.deactivate_pressure_threshold
            or edge.conflict_count >= self.deactivate_conflict_threshold
        )

        if not should_deactivate:
            uow.graph_events.add(
                GraphEvent(
                    event_uid=f'evt_{uuid4().hex}',
                    event_type='edge_revision_pending',
                    message_id=message_id,
                    trigger_edge_id=edge_id,
                    effect={
                        'trust_score': edge.trust_score,
                        'contradiction_pressure': edge.contradiction_pressure,
                        'conflict_count': edge.conflict_count,
                    },
                    note='Revision candidate reviewed but kept active.',
                )
            )
            return RevisionAction(
                edge_id=edge_id,
                action='revision_pending',
                reason='candidate_but_not_below_floor',
                before_trust=edge.trust_score,
                after_trust=edge.trust_score,
                before_pressure=edge.contradiction_pressure,
                after_pressure=edge.contradiction_pressure,
                deactivated=False,
            )

        uow.edges.deactivate(edge_id)
        deactivated = uow.edges.get_by_id(edge_id) or edge
        uow.graph_events.add(
            GraphEvent(
                event_uid=f'evt_{uuid4().hex}',
                event_type='edge_deactivated_for_revision',
                message_id=message_id,
                trigger_edge_id=edge_id,
                effect={
                    'before_trust': edge.trust_score,
                    'after_active': False,
                    'contradiction_pressure': edge.contradiction_pressure,
                },
                note='Repeated contradiction pressure crossed the revision floor; edge was deactivated.',
            )
        )
        return RevisionAction(
            edge_id=edge_id,
            action='edge_deactivated',
            reason='trust_floor_or_pressure_floor_reached',
            before_trust=edge.trust_score,
            after_trust=deactivated.trust_score,
            before_pressure=edge.contradiction_pressure,
            after_pressure=deactivated.contradiction_pressure,
            deactivated=True,
        )
