from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from core.entities.conclusion import RevisionAction
from core.entities.graph_event import GraphEvent
from core.entities.node import Node
from core.update.node_merge_service import NodeMergeRequest, NodeMergeService
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class StructureRevisionService:
    min_candidate_pressure: float = 2.0
    deactivate_trust_threshold: float = 0.2
    deactivate_pressure_threshold: float = 4.0
    deactivate_conflict_threshold: int = 4
    merge_candidate_pressure_threshold: float = 2.0
    merge_candidate_conflict_threshold: int = 2
    merge_candidate_trust_threshold: float = 0.42
    node_merge_service: NodeMergeService | None = None

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

        merge_action = self._maybe_merge_nodes(uow, edge_id=edge_id, message_id=message_id)
        if merge_action is not None:
            return merge_action

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

    def _maybe_merge_nodes(
        self,
        uow: UnitOfWork,
        *,
        edge_id: int,
        message_id: int | None = None,
    ) -> RevisionAction | None:
        edge = uow.edges.get_by_id(edge_id)
        if edge is None or not edge.is_active:
            return None
        if not self._merge_gate(edge):
            return None

        source = uow.nodes.get_by_id(edge.source_node_id)
        target = uow.nodes.get_by_id(edge.target_node_id)
        if source is None or target is None or not source.is_active or not target.is_active:
            return None
        if not self._nodes_are_merge_compatible(source, target):
            return None

        canonical, absorbed = self._choose_merge_roles(source, target)
        if canonical.id is None or absorbed.id is None or canonical.id == absorbed.id:
            return None
        if self.node_merge_service is None:
            return None

        result = self.node_merge_service.merge_with_uow(
            uow,
            NodeMergeRequest(
                canonical_node_id=canonical.id,
                absorbed_node_ids=[absorbed.id],
                message_id=message_id,
                merge_reason='revision_shallow_duplicate_merge',
                note='Revision-stage merge triggered under shallow cumulative duplicate threshold.',
            ),
        )
        return RevisionAction(
            edge_id=edge_id,
            action='node_merged',
            reason='duplicate_like_nodes_merged_during_revision',
            before_trust=edge.trust_score,
            after_trust=edge.trust_score,
            before_pressure=edge.contradiction_pressure,
            after_pressure=edge.contradiction_pressure,
            deactivated=(edge_id in result.deactivated_edge_ids),
            metadata={
                'canonical_node_id': canonical.id,
                'absorbed_node_id': absorbed.id,
                'merged_edge_ids': list(result.merged_edge_ids),
                'rewired_edge_ids': list(result.rewired_edge_ids),
                'deactivated_edge_ids': list(result.deactivated_edge_ids),
                'merged_pointer_ids': list(result.merged_pointer_ids),
                'rewired_pointer_ids': list(result.rewired_pointer_ids),
                'deactivated_pointer_ids': list(result.deactivated_pointer_ids),
            },
        )

    def _merge_gate(self, edge) -> bool:
        if not self._edge_allows_merge(edge):
            return False
        return (
            edge.contradiction_pressure >= self.merge_candidate_pressure_threshold
            or edge.conflict_count >= self.merge_candidate_conflict_threshold
            or edge.trust_score <= self.merge_candidate_trust_threshold
        )

    def _edge_allows_merge(self, edge) -> bool:
        kind = str((edge.relation_detail or {}).get('kind') or '').strip().lower()
        if edge.edge_family == 'concept':
            if edge.connect_type == 'conflict':
                return False
            if edge.connect_type == 'flow' and kind in {'subtype_of', 'is_a', 'contains', 'part_of'}:
                return False
            return True
        if edge.edge_family == 'relation':
            return edge.connect_type != 'conflict'
        return False

    def _nodes_are_merge_compatible(self, source: Node, target: Node) -> bool:
        if source.address_hash == target.address_hash:
            return True

        source_norm = (source.normalized_value or '').strip()
        target_norm = (target.normalized_value or '').strip()
        if source_norm and target_norm and source_norm == target_norm:
            return True

        source_aliases = self._alias_set(source)
        target_aliases = self._alias_set(target)
        return bool(source_aliases and target_aliases and source_aliases.intersection(target_aliases))

    def _choose_merge_roles(self, source: Node, target: Node) -> tuple[Node, Node]:
        ranked = sorted(
            [source, target],
            key=lambda item: (
                item.stability_score,
                item.trust_score,
                self._source_count(item),
                -(item.id or 0),
            ),
            reverse=True,
        )
        return ranked[0], ranked[1]

    def _alias_set(self, node: Node) -> set[str]:
        aliases: set[str] = set()
        for candidate in [node.raw_value, node.normalized_value, *(list((node.payload or {}).get('raw_aliases') or []))]:
            value = str(candidate or '').strip().lower()
            if value:
                aliases.add(value)
        return aliases

    def _source_count(self, node: Node) -> int:
        payload = dict(node.payload or {})
        return sum(int(value) for value in dict(payload.get('source_counts') or {}).values())
