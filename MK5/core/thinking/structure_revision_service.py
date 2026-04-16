from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    marker_deactivate_evidence_threshold: float = 999.0
    marker_conflict_evidence_threshold_for_deactivate: float = 999.0
    marker_merge_evidence_threshold: float = 999.0
    marker_conflict_evidence_threshold_for_merge: float = 999.0

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
    marker_deactivate_evidence_threshold: float = 999.0
    marker_conflict_evidence_threshold_for_deactivate: float = 999.0
    marker_merge_evidence_threshold: float = 999.0
    marker_conflict_evidence_threshold_for_merge: float = 999.0
    node_merge_service: NodeMergeService | None = None
    revision_edge_service: RevisionEdgeService = field(default_factory=RevisionEdgeService)
    execution_rules: tuple[RevisionExecutionRule, ...] | None = None
    rule_overrides: dict[str, dict[str, object]] | None = None

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
        marker_evidence = self.revision_edge_service.summarize_base_edge_marker_evidence(uow, base_edge=edge)
        merge_action = self._maybe_merge_nodes(
            uow,
            edge_id=edge_id,
            message_id=message_id,
            marker_summary=marker_summary,
            marker_evidence=marker_evidence,
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
            or float(marker_evidence.get(REVISION_KIND_DEACTIVATE_CANDIDATE, 0.0)) >= rule.marker_deactivate_evidence_threshold
            or float(marker_evidence.get(REVISION_KIND_CONFLICT_ASSERTION, 0.0)) >= rule.marker_conflict_evidence_threshold_for_deactivate
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
                        'rule_name': rule.name,
                        'trust_score': edge.trust_score,
                        'contradiction_pressure': edge.contradiction_pressure,
                        'conflict_count': edge.conflict_count,
                        'marker_evidence': marker_evidence,
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
                metadata={'rule_name': rule.name, 'marker_evidence': marker_evidence},
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
                    'rule_name': rule.name,
                    'before_trust': edge.trust_score,
                    'after_active': False,
                    'contradiction_pressure': edge.contradiction_pressure,
                    'marker_evidence': marker_evidence,
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
            metadata={'rule_name': rule.name, 'marker_evidence': marker_evidence},
        )

    def _maybe_merge_nodes(
        self,
        uow: UnitOfWork,
        *,
        edge_id: int,
        message_id: int | None = None,
        marker_summary: dict[str, int] | None = None,
        marker_evidence: dict[str, float] | None = None,
        rule: RevisionExecutionRule | None = None,
    ) -> RevisionAction | None:
        edge = uow.edges.get_by_id(edge_id)
        if edge is None or not edge.is_active:
            return None
        resolved_rule = rule or self._resolve_rule(edge)
        if not self._merge_gate(
            edge,
            marker_summary=marker_summary,
            marker_evidence=marker_evidence,
            rule=resolved_rule,
        ):
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
        uow.graph_events.add(
            GraphEvent(
                event_uid=f'evt_{uuid4().hex}',
                event_type='edge_revision_merge_executed',
                message_id=message_id,
                trigger_edge_id=edge_id,
                effect={
                    'rule_name': resolved_rule.name,
                    'canonical_node_id': canonical.id,
                    'absorbed_node_id': absorbed.id,
                    'marker_evidence': marker_evidence or {},
                },
                note='Revision merge executed under rule-gated thresholds.',
            )
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
                'rule_name': resolved_rule.name,
                'marker_evidence': marker_evidence or {},
            },
        )

    def _merge_gate(
        self,
        edge: Edge,
        *,
        marker_summary: dict[str, int] | None = None,
        marker_evidence: dict[str, float] | None = None,
        rule: RevisionExecutionRule,
    ) -> bool:
        if not self._edge_allows_merge(edge, rule=rule):
            return False
        marker_summary = marker_summary or {}
        marker_evidence = marker_evidence or {}
        return (
            edge.contradiction_pressure >= rule.merge_candidate_pressure_threshold
            or edge.conflict_count >= rule.merge_candidate_conflict_threshold
            or edge.trust_score <= rule.merge_candidate_trust_threshold
            or marker_summary.get(REVISION_KIND_MERGE_CANDIDATE, 0) >= rule.marker_merge_support_threshold
            or marker_summary.get(REVISION_KIND_CONFLICT_ASSERTION, 0) >= rule.marker_conflict_support_threshold_for_merge
            or float(marker_evidence.get(REVISION_KIND_MERGE_CANDIDATE, 0.0)) >= rule.marker_merge_evidence_threshold
            or float(marker_evidence.get(REVISION_KIND_CONFLICT_ASSERTION, 0.0)) >= rule.marker_conflict_evidence_threshold_for_merge
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
        base_rules = self.execution_rules or (
            self._default_rule(
                name='concept_conflict',
                edge_families=('concept',),
                connect_types=('conflict',),
                allow_merge=False,
                deactivate_trust_threshold=0.32,
                deactivate_pressure_threshold=2.4,
                deactivate_conflict_threshold=2,
                marker_deactivate_support_threshold=1,
                marker_conflict_support_threshold_for_deactivate=2,
                marker_deactivate_evidence_threshold=1.9,
                marker_conflict_evidence_threshold_for_deactivate=1.6,
            ),
            self._default_rule(
                name='relation_conflict',
                edge_families=('relation',),
                connect_types=('conflict',),
                allow_merge=False,
                deactivate_trust_threshold=0.28,
                deactivate_pressure_threshold=3.0,
                deactivate_conflict_threshold=3,
                marker_deactivate_support_threshold=2,
                marker_conflict_support_threshold_for_deactivate=3,
                marker_deactivate_evidence_threshold=2.6,
                marker_conflict_evidence_threshold_for_deactivate=2.2,
            ),
            self._default_rule(
                name='concept_opposite',
                edge_families=('concept',),
                connect_types=('opposite',),
                allow_merge=False,
                deactivate_trust_threshold=0.3,
                deactivate_pressure_threshold=2.8,
                deactivate_conflict_threshold=2,
                marker_conflict_support_threshold_for_deactivate=3,
                marker_conflict_evidence_threshold_for_deactivate=2.0,
            ),
            self._default_rule(
                name='concept_flow',
                edge_families=('concept',),
                connect_types=('flow',),
                allow_merge=True,
                deactivate_trust_threshold=0.2,
                deactivate_pressure_threshold=4.2,
                deactivate_conflict_threshold=4,
                merge_candidate_pressure_threshold=2.4,
                merge_candidate_conflict_threshold=3,
                merge_candidate_trust_threshold=0.38,
                marker_merge_support_threshold=3,
                marker_conflict_support_threshold_for_merge=5,
                marker_merge_evidence_threshold=4.8,
                marker_conflict_evidence_threshold_for_merge=4.2,
            ),
            self._default_rule(
                name='concept_neutral',
                edge_families=('concept',),
                connect_types=('neutral',),
                allow_merge=True,
                deactivate_trust_threshold=0.22,
                deactivate_pressure_threshold=3.8,
                deactivate_conflict_threshold=3,
                merge_candidate_pressure_threshold=2.0,
                merge_candidate_conflict_threshold=2,
                merge_candidate_trust_threshold=0.42,
                marker_merge_evidence_threshold=3.6,
            ),
            self._default_rule(
                name='relation_neutral',
                edge_families=('relation',),
                connect_types=('neutral',),
                allow_merge=True,
                deactivate_trust_threshold=0.18,
                deactivate_pressure_threshold=4.6,
                deactivate_conflict_threshold=5,
                marker_deactivate_support_threshold=2,
                marker_conflict_support_threshold_for_deactivate=6,
                merge_candidate_pressure_threshold=2.2,
                merge_candidate_conflict_threshold=2,
                merge_candidate_trust_threshold=0.4,
                marker_deactivate_evidence_threshold=3.0,
                marker_merge_evidence_threshold=4.2,
            ),
            self._default_rule(name='concept_any', edge_families=('concept',)),
            self._default_rule(name='relation_any', edge_families=('relation',)),
            self._default_rule(name='fallback'),
        )
        return self._apply_rule_overrides(base_rules)

    def _default_rule(
        self,
        *,
        name: str,
        edge_families: tuple[str, ...] = (),
        connect_types: tuple[str, ...] = (),
        allow_merge: bool = True,
        deactivate_trust_threshold: float | None = None,
        deactivate_pressure_threshold: float | None = None,
        deactivate_conflict_threshold: int | None = None,
        merge_candidate_pressure_threshold: float | None = None,
        merge_candidate_conflict_threshold: int | None = None,
        merge_candidate_trust_threshold: float | None = None,
        marker_deactivate_support_threshold: int | None = None,
        marker_conflict_support_threshold_for_deactivate: int | None = None,
        marker_merge_support_threshold: int | None = None,
        marker_conflict_support_threshold_for_merge: int | None = None,
        marker_deactivate_evidence_threshold: float | None = None,
        marker_conflict_evidence_threshold_for_deactivate: float | None = None,
        marker_merge_evidence_threshold: float | None = None,
        marker_conflict_evidence_threshold_for_merge: float | None = None,
    ) -> RevisionExecutionRule:
        return RevisionExecutionRule(
            name=name,
            edge_families=edge_families,
            connect_types=connect_types,
            allow_merge=allow_merge,
            deactivate_trust_threshold=(
                self.deactivate_trust_threshold
                if deactivate_trust_threshold is None
                else deactivate_trust_threshold
            ),
            deactivate_pressure_threshold=(
                self.deactivate_pressure_threshold
                if deactivate_pressure_threshold is None
                else deactivate_pressure_threshold
            ),
            deactivate_conflict_threshold=(
                self.deactivate_conflict_threshold
                if deactivate_conflict_threshold is None
                else deactivate_conflict_threshold
            ),
            merge_candidate_pressure_threshold=(
                self.merge_candidate_pressure_threshold
                if merge_candidate_pressure_threshold is None
                else merge_candidate_pressure_threshold
            ),
            merge_candidate_conflict_threshold=(
                self.merge_candidate_conflict_threshold
                if merge_candidate_conflict_threshold is None
                else merge_candidate_conflict_threshold
            ),
            merge_candidate_trust_threshold=(
                self.merge_candidate_trust_threshold
                if merge_candidate_trust_threshold is None
                else merge_candidate_trust_threshold
            ),
            marker_deactivate_support_threshold=(
                self.marker_deactivate_support_threshold
                if marker_deactivate_support_threshold is None
                else marker_deactivate_support_threshold
            ),
            marker_conflict_support_threshold_for_deactivate=(
                self.marker_conflict_support_threshold_for_deactivate
                if marker_conflict_support_threshold_for_deactivate is None
                else marker_conflict_support_threshold_for_deactivate
            ),
            marker_merge_support_threshold=(
                self.marker_merge_support_threshold
                if marker_merge_support_threshold is None
                else marker_merge_support_threshold
            ),
            marker_conflict_support_threshold_for_merge=(
                self.marker_conflict_support_threshold_for_merge
                if marker_conflict_support_threshold_for_merge is None
                else marker_conflict_support_threshold_for_merge
            ),
            marker_deactivate_evidence_threshold=(
                self.marker_deactivate_evidence_threshold
                if marker_deactivate_evidence_threshold is None
                else marker_deactivate_evidence_threshold
            ),
            marker_conflict_evidence_threshold_for_deactivate=(
                self.marker_conflict_evidence_threshold_for_deactivate
                if marker_conflict_evidence_threshold_for_deactivate is None
                else marker_conflict_evidence_threshold_for_deactivate
            ),
            marker_merge_evidence_threshold=(
                self.marker_merge_evidence_threshold
                if marker_merge_evidence_threshold is None
                else marker_merge_evidence_threshold
            ),
            marker_conflict_evidence_threshold_for_merge=(
                self.marker_conflict_evidence_threshold_for_merge
                if marker_conflict_evidence_threshold_for_merge is None
                else marker_conflict_evidence_threshold_for_merge
            ),
        )

    def _apply_rule_overrides(
        self,
        rules: tuple[RevisionExecutionRule, ...],
    ) -> tuple[RevisionExecutionRule, ...]:
        overrides = dict(self.rule_overrides or {})
        if not overrides:
            return rules
        result: list[RevisionExecutionRule] = []
        valid_keys = set(RevisionExecutionRule.__dataclass_fields__.keys()) - {'name'}
        for rule in rules:
            raw_override = dict(overrides.get(rule.name) or {})
            if not raw_override:
                result.append(rule)
                continue
            updates: dict[str, object] = {}
            for key, raw_value in raw_override.items():
                if key not in valid_keys:
                    continue
                coerced = self._coerce_override_value(getattr(rule, key), raw_value)
                if coerced is not None:
                    updates[key] = coerced
            result.append(replace(rule, **updates) if updates else rule)
        return tuple(result)

    def _coerce_override_value(self, current: object, raw_value: object) -> object | None:
        try:
            if isinstance(current, bool):
                if isinstance(raw_value, bool):
                    return raw_value
                token = str(raw_value or '').strip().lower()
                if token in {'true', '1', 'yes'}:
                    return True
                if token in {'false', '0', 'no'}:
                    return False
                return None
            if isinstance(current, int) and not isinstance(current, bool):
                return int(raw_value)
            if isinstance(current, float):
                return float(raw_value)
            if isinstance(current, tuple):
                if isinstance(raw_value, (list, tuple)):
                    return tuple(str(item) for item in raw_value if str(item).strip())
                token = str(raw_value or '').strip()
                return tuple(item.strip() for item in token.split(',') if item.strip())
            return raw_value
        except (TypeError, ValueError):
            return None
