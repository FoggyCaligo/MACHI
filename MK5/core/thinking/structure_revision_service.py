from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from core.entities.conclusion import RevisionAction
from core.entities.edge import Edge
from core.entities.graph_event import GraphEvent
from core.entities.node import Node
from core.update.node_merge_service import NodeMergeRequest, NodeMergeService
from core.update.revision_edge_service import (
    REVISION_KIND_CONFLICT_ASSERTION,
    REVISION_KIND_DEACTIVATE_CANDIDATE,
    REVISION_KIND_MERGE_CANDIDATE,
    REVISION_KIND_PENDING,
    RevisionEdgeService,
)
from storage.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class RevisionExecutionRule:
    name: str
    edge_families: tuple[str, ...] = ()
    connect_types: tuple[str, ...] = ()
    allow_merge: bool = True
    deactivate_trust_threshold: float = 0.2
    deactivate_pressure_threshold: float = 4.0
    deactivate_conflict_threshold: int = 4
    merge_candidate_pressure_threshold: float = 2.0
    merge_candidate_conflict_threshold: int = 2
    merge_candidate_trust_threshold: float = 0.42
    marker_deactivate_support_threshold: int = 2
    marker_conflict_support_threshold_for_deactivate: int = 6
    marker_merge_support_threshold: int = 2
    marker_conflict_support_threshold_for_merge: int = 4

    def matches(self, edge: Edge) -> bool:
        if self.edge_families and edge.edge_family not in self.edge_families:
            return False
        if self.connect_types and edge.connect_type not in self.connect_types:
            return False
        return True


@dataclass(slots=True)
class StructureRevisionService:
    min_candidate_pressure: float = 2.0
    deactivate_trust_threshold: float = 0.2
    deactivate_pressure_threshold: float = 4.0
    deactivate_conflict_threshold: int = 4
    merge_candidate_pressure_threshold: float = 2.0
    merge_candidate_conflict_threshold: int = 2
    merge_candidate_trust_threshold: float = 0.42
    marker_deactivate_support_threshold: int = 2
    marker_conflict_support_threshold_for_deactivate: int = 6
    marker_merge_support_threshold: int = 2
    marker_conflict_support_threshold_for_merge: int = 4
    node_merge_service: NodeMergeService | None = None
    revision_edge_service: RevisionEdgeService = field(default_factory=RevisionEdgeService)
    execution_rules: tuple[RevisionExecutionRule, ...] | None = None

    def review_candidates(
        self,
        uow: UnitOfWork,
        *,
        message_id: int | None = None,
        limit: int = 100,
    ) -> list[RevisionAction]:
        candidate_ids = self._collect_candidate_edge_ids(uow, limit=limit)
        if not candidate_ids:
            return []
        actions: list[RevisionAction] = []
        for edge_id in candidate_ids:
            action = self._review_one(uow, edge_id, message_id=message_id)
            if action is not None:
                actions.append(action)
        return actions

    def _collect_candidate_edge_ids(self, uow: UnitOfWork, *, limit: int) -> list[int]:
        # Marker-edge only: edge-first 정책의 기준 후보 소스
        return self.revision_edge_service.list_candidate_base_edge_ids(uow, limit=limit)

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
        rule = self._resolve_rule(edge)

        marker_summary = self.revision_edge_service.summarize_base_edge_markers(uow, base_edge=edge)
        merge_action = self._maybe_merge_nodes(
            uow,
            edge_id=edge_id,
            message_id=message_id,
            marker_summary=marker_summary,
            rule=rule,
        )
        if merge_action is not None:
            return merge_action

        should_deactivate = (
            edge.trust_score <= rule.deactivate_trust_threshold
            or edge.contradiction_pressure >= rule.deactivate_pressure_threshold
            or edge.conflict_count >= rule.deactivate_conflict_threshold
            or marker_summary.get(REVISION_KIND_DEACTIVATE_CANDIDATE, 0) >= rule.marker_deactivate_support_threshold
            or marker_summary.get(REVISION_KIND_CONFLICT_ASSERTION, 0) >= rule.marker_conflict_support_threshold_for_deactivate
        )

        if not should_deactivate:
            self.revision_edge_service.record_revision_marker(
                uow,
                base_edge=edge,
                kind=REVISION_KIND_PENDING,
                reason='candidate_but_not_below_floor',
                message_id=message_id,
                status='open',
                metadata={
                    'trust_score': edge.trust_score,
                    'contradiction_pressure': edge.contradiction_pressure,
                    'conflict_count': edge.conflict_count,
                },
            )
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
        self.revision_edge_service.record_revision_marker(
            uow,
            base_edge=edge,
            kind=REVISION_KIND_DEACTIVATE_CANDIDATE,
            reason='trust_floor_or_pressure_floor_reached',
            message_id=message_id,
            status='executed',
            metadata={
                'before_trust': edge.trust_score,
                'contradiction_pressure': edge.contradiction_pressure,
                'conflict_count': edge.conflict_count,
            },
        )
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
        marker_summary: dict[str, int] | None = None,
        rule: RevisionExecutionRule | None = None,
    ) -> RevisionAction | None:
        edge = uow.edges.get_by_id(edge_id)
        if edge is None or not edge.is_active:
            return None
        resolved_rule = rule or self._resolve_rule(edge)
        if not self._merge_gate(edge, marker_summary=marker_summary, rule=resolved_rule):
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
        self.revision_edge_service.record_revision_marker(
            uow,
            base_edge=edge,
            kind=REVISION_KIND_MERGE_CANDIDATE,
            reason='duplicate_like_nodes_merged_during_revision',
            message_id=message_id,
            status='executed',
            metadata={
                'canonical_node_id': canonical.id,
                'absorbed_node_id': absorbed.id,
            },
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

    def _merge_gate(
        self,
        edge: Edge,
        *,
        marker_summary: dict[str, int] | None = None,
        rule: RevisionExecutionRule,
    ) -> bool:
        if not self._edge_allows_merge(edge, rule=rule):
            return False
        marker_summary = marker_summary or {}
        return (
            edge.contradiction_pressure >= rule.merge_candidate_pressure_threshold
            or edge.conflict_count >= rule.merge_candidate_conflict_threshold
            or edge.trust_score <= rule.merge_candidate_trust_threshold
            or marker_summary.get(REVISION_KIND_MERGE_CANDIDATE, 0) >= rule.marker_merge_support_threshold
            or marker_summary.get(REVISION_KIND_CONFLICT_ASSERTION, 0) >= rule.marker_conflict_support_threshold_for_merge
        )

    def _edge_allows_merge(self, edge: Edge, *, rule: RevisionExecutionRule) -> bool:
        if not rule.allow_merge:
            return False
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

    def _resolve_rule(self, edge: Edge) -> RevisionExecutionRule:
        for rule in self._rules():
            if rule.matches(edge):
                return rule
        return self._default_rule(name='fallback')

    def _rules(self) -> tuple[RevisionExecutionRule, ...]:
        return self.execution_rules or (
            self._default_rule(name='concept_conflict', edge_families=('concept',), connect_types=('conflict',), allow_merge=False),
            self._default_rule(name='relation_conflict', edge_families=('relation',), connect_types=('conflict',), allow_merge=False),
            self._default_rule(name='concept_any', edge_families=('concept',)),
            self._default_rule(name='relation_any', edge_families=('relation',)),
            self._default_rule(name='fallback'),
        )

    def _default_rule(
        self,
        *,
        name: str,
        edge_families: tuple[str, ...] = (),
        connect_types: tuple[str, ...] = (),
        allow_merge: bool = True,
    ) -> RevisionExecutionRule:
        return RevisionExecutionRule(
            name=name,
            edge_families=edge_families,
            connect_types=connect_types,
            allow_merge=allow_merge,
            deactivate_trust_threshold=self.deactivate_trust_threshold,
            deactivate_pressure_threshold=self.deactivate_pressure_threshold,
            deactivate_conflict_threshold=self.deactivate_conflict_threshold,
            merge_candidate_pressure_threshold=self.merge_candidate_pressure_threshold,
            merge_candidate_conflict_threshold=self.merge_candidate_conflict_threshold,
            merge_candidate_trust_threshold=self.merge_candidate_trust_threshold,
            marker_deactivate_support_threshold=self.marker_deactivate_support_threshold,
            marker_conflict_support_threshold_for_deactivate=self.marker_conflict_support_threshold_for_deactivate,
            marker_merge_support_threshold=self.marker_merge_support_threshold,
            marker_conflict_support_threshold_for_merge=self.marker_conflict_support_threshold_for_merge,
        )
