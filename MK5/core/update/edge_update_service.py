from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from core.entities.graph_event import GraphEvent
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class EdgeUpdateService:
    """Dedicated layer for modifying edge state.

    Callers (TrustManager, ConceptDifferentiationService, etc.) decide the
    semantic meaning of each change. This service only applies the mechanics:
    support, conflict, deactivation.

    No semantic interpretation happens here.
    """

    support_trust_delta: float = 0.025
    conflict_trust_delta: float = -0.030
    conflict_pressure_delta: float = 1.0
    deactivation_trust_threshold: float = 0.08
    revision_pressure_threshold: float = 2.0

    def apply_support(
        self,
        uow: UnitOfWork,
        edge_id: int,
        *,
        message_id: int | None = None,
        delta: int = 1,
        trust_delta: float | None = None,
    ) -> None:
        actual_delta = trust_delta if trust_delta is not None else self.support_trust_delta
        uow.edges.bump_support(edge_id, delta=delta, trust_delta=actual_delta)
        uow.graph_events.add(GraphEvent(
            event_uid=f'evt-{uuid4().hex}',
            event_type='edge_supported',
            message_id=message_id,
            trigger_edge_id=edge_id,
            parsed_input={'delta': delta, 'trust_delta': actual_delta},
            effect={'action': 'support_applied'},
        ))

    def apply_conflict(
        self,
        uow: UnitOfWork,
        edge_id: int,
        *,
        message_id: int | None = None,
        delta: int = 1,
        pressure_delta: float | None = None,
        trust_delta: float | None = None,
    ) -> None:
        actual_pressure = pressure_delta if pressure_delta is not None else self.conflict_pressure_delta
        actual_trust = trust_delta if trust_delta is not None else self.conflict_trust_delta
        uow.edges.bump_conflict(
            edge_id,
            delta=delta,
            pressure_delta=actual_pressure,
            trust_delta=actual_trust,
        )
        # Auto-flag as revision candidate when pressure accumulates
        edge = uow.edges.get_by_id(edge_id)
        if edge is not None and edge.is_active and not edge.revision_candidate_flag:
            if (
                edge.contradiction_pressure >= self.revision_pressure_threshold
                or edge.conflict_count > edge.support_count
            ):
                uow.edges.set_revision_candidate(edge_id, flag=True)

        uow.graph_events.add(GraphEvent(
            event_uid=f'evt-{uuid4().hex}',
            event_type='edge_conflict_applied',
            message_id=message_id,
            trigger_edge_id=edge_id,
            parsed_input={
                'delta': delta,
                'pressure_delta': actual_pressure,
                'trust_delta': actual_trust,
            },
            effect={'action': 'conflict_applied'},
        ))

    def deactivate_if_below_threshold(
        self,
        uow: UnitOfWork,
        edge_id: int,
        *,
        message_id: int | None = None,
        trust_threshold: float | None = None,
    ) -> bool:
        threshold = trust_threshold if trust_threshold is not None else self.deactivation_trust_threshold
        edge = uow.edges.get_by_id(edge_id)
        if edge is None or not edge.is_active:
            return False
        if edge.trust_score > threshold:
            return False
        uow.edges.deactivate(edge_id)
        uow.graph_events.add(GraphEvent(
            event_uid=f'evt-{uuid4().hex}',
            event_type='edge_deactivated',
            message_id=message_id,
            trigger_edge_id=edge_id,
            parsed_input={'trust_score': edge.trust_score, 'threshold': threshold},
            effect={'action': 'deactivated', 'reason': 'trust_below_threshold'},
        ))
        return True

    def deactivate(
        self,
        uow: UnitOfWork,
        edge_id: int,
        *,
        message_id: int | None = None,
        reason: str = 'explicit_deactivation',
    ) -> None:
        uow.edges.deactivate(edge_id)
        uow.graph_events.add(GraphEvent(
            event_uid=f'evt-{uuid4().hex}',
            event_type='edge_deactivated',
            message_id=message_id,
            trigger_edge_id=edge_id,
            parsed_input={'reason': reason},
            effect={'action': 'deactivated'},
        ))
