from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from core.entities.conclusion import ContradictionSignal, RevisionAction
from core.entities.edge import Edge
from core.entities.graph_event import GraphEvent
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
            conflict_edge_id = self._create_or_support_conflict_edge(
                uow,
                edge=edge,
                signal=signal,
                message_id=message_id,
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

    def _create_or_support_conflict_edge(
        self,
        uow: UnitOfWork,
        *,
        edge: Edge,
        signal: ContradictionSignal,
        message_id: int | None,
    ) -> int | None:
        existing = uow.edges.find_active_relation(
            edge.source_node_id,
            edge.target_node_id,
            edge_family=edge.edge_family,
            connect_type='conflict',
        )

        if existing is None:
            relation_detail = {
                'note': 'Conflict edge derived from contradiction signal.',
                'source_edge_ids': [edge.id] if edge.id is not None else [],
                'reasons': [signal.reason],
                'latest_signal_score': signal.score,
                'created_from_message_id': message_id,
            }
            created = uow.edges.add(
                Edge(
                    edge_uid=f'edge_{uuid4().hex}',
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    edge_family=edge.edge_family,
                    connect_type='conflict',
                    relation_detail=relation_detail,
                    edge_weight=max(0.1, edge.edge_weight),
                    trust_score=max(0.35, min(0.95, signal.score)),
                    support_count=1,
                    created_from_event_id=edge.created_from_event_id,
                )
            )
            uow.graph_events.add(
                GraphEvent(
                    event_uid=f'evt_{uuid4().hex}',
                    event_type='conflict_edge_created',
                    message_id=message_id,
                    trigger_edge_id=created.id,
                    parsed_input={
                        'source_edge_id': edge.id,
                        'severity': signal.severity,
                        'reason': signal.reason,
                    },
                    effect={
                        'edge_family': edge.edge_family,
                        'connect_type': 'conflict',
                        'source_node_id': edge.source_node_id,
                        'target_node_id': edge.target_node_id,
                    },
                    note='Conflict edge created from contradiction signal.',
                )
            )
            return created.id

        relation_detail = dict(existing.relation_detail or {})
        source_edge_ids = list(relation_detail.get('source_edge_ids') or [])
        if edge.id is not None and edge.id not in source_edge_ids:
            source_edge_ids.append(edge.id)
        relation_detail['source_edge_ids'] = source_edge_ids

        reasons = list(relation_detail.get('reasons') or [])
        if signal.reason not in reasons:
            reasons.append(signal.reason)
        relation_detail['reasons'] = reasons[-8:]
        relation_detail['latest_signal_score'] = signal.score
        relation_detail['last_message_id'] = message_id
        uow.edges.update_relation_detail(existing.id or 0, relation_detail)
        uow.edges.bump_support(existing.id or 0, delta=1, trust_delta=max(0.02, signal.score * 0.05))
        uow.graph_events.add(
            GraphEvent(
                event_uid=f'evt_{uuid4().hex}',
                event_type='conflict_edge_supported',
                message_id=message_id,
                trigger_edge_id=existing.id,
                parsed_input={
                    'source_edge_id': edge.id,
                    'severity': signal.severity,
                    'reason': signal.reason,
                },
                effect={
                    'delta': 1,
                    'trust_delta': max(0.02, signal.score * 0.05),
                },
                note='Existing conflict edge reinforced by contradiction signal.',
            )
        )
        return existing.id

    def _deltas_for(self, signal: ContradictionSignal) -> tuple[float, float]:
        if signal.reason == 'opposite_connect_type':
            return self.medium_trust_delta * 0.75, self.medium_pressure_delta * 0.8
        if signal.severity == 'high':
            return self.high_trust_delta, self.high_pressure_delta
        return self.medium_trust_delta, self.medium_pressure_delta
