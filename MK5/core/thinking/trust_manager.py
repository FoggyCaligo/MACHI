from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from core.entities.conclusion import ContradictionSignal, RevisionAction
from core.entities.graph_event import GraphEvent
from core.update.revision_edge_service import RevisionEdgeService
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class TrustManager:
    medium_trust_delta: float = -0.08
    medium_pressure_delta: float = 0.75
    high_trust_delta: float = -0.15
    high_pressure_delta: float = 1.25
    revision_candidate_pressure_threshold: float = 2.0
    revision_candidate_conflict_threshold: int = 2
    revision_candidate_trust_threshold: float = 0.42
    revision_edge_service: RevisionEdgeService = field(default_factory=RevisionEdgeService)

    def apply_signal(
        self,
        uow: UnitOfWork,
        signal: ContradictionSignal,
        *,
        message_id: int | None = None,
    ) -> RevisionAction | None:
        edge = uow.edges.get_by_id(signal.edge_id)
        if edge is None or not edge.is_active:
            return None

        trust_delta, pressure_delta = self._deltas_for(signal)
        before_trust = edge.trust_score
        before_pressure = edge.contradiction_pressure

        uow.edges.bump_conflict(
            signal.edge_id,
            delta=1,
            pressure_delta=pressure_delta,
            trust_delta=trust_delta,
        )
        updated = uow.edges.get_by_id(signal.edge_id)
        if updated is None:
            return None

        conflict_edge_id: int | None = None
        if not edge.is_conflict:
            conflict_edge_result = self.revision_edge_service.record_conflict_assertion(
                uow,
                base_edge=edge,
                reason=signal.reason,
                signal_score=signal.score,
                message_id=message_id,
            )
            conflict_edge_id = conflict_edge_result.edge_id
            if conflict_edge_id is not None:
                event_type = 'conflict_edge_created' if conflict_edge_result.action == 'created' else 'conflict_edge_supported'
                effect = (
                    {
                        'edge_family': edge.edge_family,
                        'connect_type': 'conflict',
                        'source_node_id': edge.source_node_id,
                        'target_node_id': edge.target_node_id,
                    }
                    if conflict_edge_result.action == 'created'
                    else {
                        'delta': 1,
                        'trust_delta': max(0.02, signal.score * 0.05),
                    }
                )
                uow.graph_events.add(
                    GraphEvent(
                        event_uid=f'evt_{uuid4().hex}',
                        event_type=event_type,
                        message_id=message_id,
                        trigger_edge_id=conflict_edge_id,
                        parsed_input={
                            'source_edge_id': edge.id,
                            'severity': signal.severity,
                            'reason': signal.reason,
                        },
                        effect=effect,
                        note='Conflict revision edge updated from contradiction signal.',
                    )
                )

        should_flag = (
            updated.contradiction_pressure >= self.revision_candidate_pressure_threshold
            or updated.conflict_count >= self.revision_candidate_conflict_threshold
            or updated.trust_score <= self.revision_candidate_trust_threshold
        )
        if should_flag and not updated.revision_candidate_flag:
            uow.edges.set_revision_candidate(signal.edge_id, flag=True)
            updated = uow.edges.get_by_id(signal.edge_id) or updated

        uow.graph_events.add(
            GraphEvent(
                event_uid=f'evt_{uuid4().hex}',
                event_type='edge_conflict_registered',
                message_id=message_id,
                trigger_edge_id=signal.edge_id,
                parsed_input={
                    'severity': signal.severity,
                    'reason': signal.reason,
                    'score': signal.score,
                },
                effect={
                    'trust_delta': trust_delta,
                    'pressure_delta': pressure_delta,
                    'revision_candidate': should_flag,
                    'conflict_edge_id': conflict_edge_id,
                },
                note='Contradiction signal lowered trust and increased contradiction pressure.',
            )
        )

        return RevisionAction(
            edge_id=signal.edge_id,
            action='conflict_registered',
            reason=signal.reason,
            before_trust=before_trust,
            after_trust=updated.trust_score,
            before_pressure=before_pressure,
            after_pressure=updated.contradiction_pressure,
            deactivated=False,
            metadata={
                'severity': signal.severity,
                'revision_candidate': should_flag,
                'conflict_edge_id': conflict_edge_id,
            },
        )

    def _deltas_for(self, signal: ContradictionSignal) -> tuple[float, float]:
        if signal.reason == 'opposite_connect_type':
            return self.medium_trust_delta * 0.75, self.medium_pressure_delta * 0.8
        if signal.severity == 'high':
            return self.high_trust_delta, self.high_pressure_delta
        return self.medium_trust_delta, self.medium_pressure_delta
