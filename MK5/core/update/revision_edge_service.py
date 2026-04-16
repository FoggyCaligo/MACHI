from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from core.entities.edge import Edge
from storage.unit_of_work import UnitOfWork

REVISION_PURPOSE = 'revision'
REVISION_MARKER_CONFLICT_SUPPORT = 'conflict_support'
REVISION_MARKER_NEUTRAL_SUPPORT = 'neutral_support'
# Deprecated aliases kept for compatibility with older tests/callers.
REVISION_KIND_CONFLICT_ASSERTION = REVISION_MARKER_CONFLICT_SUPPORT
REVISION_KIND_PENDING = REVISION_MARKER_NEUTRAL_SUPPORT
REVISION_KIND_DEACTIVATE_CANDIDATE = REVISION_MARKER_NEUTRAL_SUPPORT
REVISION_KIND_MERGE_CANDIDATE = REVISION_MARKER_NEUTRAL_SUPPORT


@dataclass(slots=True)
class RevisionEdgeUpsertResult:
    edge_id: int | None
    action: str


@dataclass(slots=True)
class RevisionEdgeService:
    max_reasons: int = 12
    marker_scan_limit: int = 400

    def record_conflict_assertion(
        self,
        uow: UnitOfWork,
        *,
        base_edge: Edge,
        reason: str,
        signal_score: float,
        message_id: int | None,
    ) -> RevisionEdgeUpsertResult:
        relation_detail = self._base_detail(
            reason=reason,
            message_id=message_id,
            source_edge_id=base_edge.id,
            signal_score=signal_score,
        )
        return self._upsert_revision_edge(
            uow,
            base_edge=base_edge,
            connect_type='conflict',
            relation_detail=relation_detail,
            initial_trust=max(0.35, min(0.95, signal_score)),
            trust_delta=max(0.02, signal_score * 0.05),
        )

    def record_revision_marker(
        self,
        uow: UnitOfWork,
        *,
        base_edge: Edge,
        reason: str,
        message_id: int | None,
        marker_role: str = REVISION_MARKER_NEUTRAL_SUPPORT,
        status: str = 'open',
        metadata: dict[str, Any] | None = None,
        kind: str | None = None,  # backward-compatible input; ignored
    ) -> RevisionEdgeUpsertResult:
        relation_detail = self._base_detail(
            reason=reason,
            message_id=message_id,
            source_edge_id=base_edge.id,
        )
        relation_detail['marker_role'] = marker_role
        relation_detail['status'] = status
        if metadata:
            relation_detail['metadata'] = dict(metadata)
        return self._upsert_revision_edge(
            uow,
            base_edge=base_edge,
            connect_type='neutral',
            relation_detail=relation_detail,
            initial_trust=max(0.3, min(0.85, base_edge.trust_score * 0.9)),
            trust_delta=0.01,
        )

    def _upsert_revision_edge(
        self,
        uow: UnitOfWork,
        *,
        base_edge: Edge,
        connect_type: str,
        relation_detail: dict[str, Any],
        initial_trust: float,
        trust_delta: float,
    ) -> RevisionEdgeUpsertResult:
        existing = self._find_existing_revision_edge(
            uow,
            base_edge=base_edge,
            connect_type=connect_type,
        )
        if existing is None:
            created = uow.edges.add(
                Edge(
                    edge_uid=f'revision-{uuid4().hex}',
                    source_node_id=base_edge.source_node_id,
                    target_node_id=base_edge.target_node_id,
                    edge_family=base_edge.edge_family,
                    connect_type=connect_type,
                    relation_detail=relation_detail,
                    edge_weight=max(0.1, base_edge.edge_weight),
                    trust_score=initial_trust,
                    support_count=1,
                    created_from_event_id=base_edge.created_from_event_id,
                )
            )
            return RevisionEdgeUpsertResult(edge_id=created.id, action='created')

        merged_detail = self._merge_detail(
            existing.relation_detail,
            relation_detail,
        )
        if existing.id is not None:
            uow.edges.update_relation_detail(existing.id, merged_detail)
            uow.edges.bump_support(existing.id, delta=1, trust_delta=trust_delta)
        return RevisionEdgeUpsertResult(edge_id=existing.id, action='supported')

    def list_candidate_base_edge_ids(
        self,
        uow: UnitOfWork,
        *,
        limit: int = 200,
    ) -> list[int]:
        marker_edges = uow.edges.list_active_revision_markers(
            limit=max(limit * 4, self.marker_scan_limit),
        )
        collected: list[int] = []
        for marker in marker_edges:
            base_id = self._extract_primary_source_edge_id(marker.relation_detail)
            if base_id is None:
                continue
            if base_id not in collected:
                collected.append(base_id)
            if len(collected) >= limit:
                break
        return collected

    def summarize_base_edge_markers(self, uow: UnitOfWork, *, base_edge: Edge) -> dict[str, int]:
        rows = self._list_markers_for_base_edge(uow, base_edge=base_edge)
        summary = {
            'total_support': 0,
            'conflict_support': 0,
            'neutral_support': 0,
        }
        for marker in rows:
            support = max(1, int(marker.support_count))
            summary['total_support'] += support
            if marker.connect_type == 'conflict':
                summary['conflict_support'] += support
            else:
                summary['neutral_support'] += support
        return summary

    def summarize_base_edge_marker_evidence(self, uow: UnitOfWork, *, base_edge: Edge) -> dict[str, float]:
        rows = self._list_markers_for_base_edge(uow, base_edge=base_edge)
        summary = {
            'total_evidence': 0.0,
            'conflict_support': 0.0,
            'neutral_support': 0.0,
        }
        for marker in rows:
            evidence = self._marker_evidence_score(marker)
            summary['total_evidence'] += evidence
            if marker.connect_type == 'conflict':
                summary['conflict_support'] += evidence
            else:
                summary['neutral_support'] += evidence
        return {key: round(float(value), 6) for key, value in summary.items()}

    def _find_existing_revision_edge(
        self,
        uow: UnitOfWork,
        *,
        base_edge: Edge,
        connect_type: str,
    ) -> Edge | None:
        candidates = uow.edges.list_outgoing(
            base_edge.source_node_id,
            edge_families=[base_edge.edge_family],
            connect_types=[connect_type],
            active_only=True,
        )
        for edge in candidates:
            if edge.target_node_id != base_edge.target_node_id:
                continue
            detail = dict(edge.relation_detail or {})
            if detail.get('purpose') != REVISION_PURPOSE:
                continue
            return edge
        return None

    def _base_detail(
        self,
        *,
        reason: str,
        message_id: int | None,
        source_edge_id: int | None,
        signal_score: float | None = None,
    ) -> dict[str, Any]:
        reasons = [reason] if reason else []
        detail: dict[str, Any] = {
            'purpose': REVISION_PURPOSE,
            'status': 'open',
            'source_edge_ids': [source_edge_id] if source_edge_id is not None else [],
            'reasons': reasons,
            'latest_reason': reason,
            'created_from_message_id': message_id,
            'last_message_id': message_id,
        }
        if signal_score is not None:
            detail['latest_signal_score'] = signal_score
        return detail

    def _merge_detail(
        self,
        existing: dict[str, Any] | None,
        incoming: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current = dict(existing or {})
        new = dict(incoming or {})
        reasons = list(current.get('reasons') or [])
        for item in list(new.get('reasons') or []):
            token = str(item or '').strip()
            if token and token not in reasons:
                reasons.append(token)
        source_edge_ids = list(current.get('source_edge_ids') or [])
        for item in list(new.get('source_edge_ids') or []):
            try:
                edge_id = int(item)
            except (TypeError, ValueError):
                continue
            if edge_id not in source_edge_ids:
                source_edge_ids.append(edge_id)

        merged = current
        merged.update(new)
        merged['reasons'] = reasons[-self.max_reasons:]
        merged['source_edge_ids'] = source_edge_ids
        if not merged.get('latest_reason'):
            merged['latest_reason'] = reasons[-1] if reasons else ''
        return merged

    def _extract_primary_source_edge_id(self, detail: dict[str, Any] | None) -> int | None:
        payload = dict(detail or {})
        source_edge_ids = list(payload.get('source_edge_ids') or [])
        for item in source_edge_ids:
            try:
                value = int(item)
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return None

    def _list_markers_for_base_edge(self, uow: UnitOfWork, *, base_edge: Edge) -> list[Edge]:
        if base_edge.id is None:
            return []
        candidates = uow.edges.list_outgoing(
            base_edge.source_node_id,
            edge_families=[base_edge.edge_family],
            connect_types=['neutral', 'conflict'],
            active_only=True,
            limit=self.marker_scan_limit,
        )
        rows: list[Edge] = []
        for edge in candidates:
            if edge.target_node_id != base_edge.target_node_id:
                continue
            detail = dict(edge.relation_detail or {})
            if detail.get('purpose') != REVISION_PURPOSE:
                continue
            source_ids = list(detail.get('source_edge_ids') or [])
            if base_edge.id not in source_ids:
                continue
            rows.append(edge)
        return rows

    def _marker_evidence_score(self, marker: Edge) -> float:
        detail = dict(marker.relation_detail or {})
        status = str(detail.get('status') or '').strip().lower()
        raw_signal = detail.get('latest_signal_score')

        support_factor = max(1.0, float(marker.support_count))
        trust_factor = max(0.1, min(1.6, 0.5 + float(marker.trust_score)))
        status_factor = 1.12 if status == 'executed' else 1.0
        connect_type_factor = 1.1 if marker.connect_type == 'conflict' else 1.0

        signal_factor = 1.0
        if raw_signal is not None:
            try:
                signal = float(raw_signal)
            except (TypeError, ValueError):
                signal = 0.0
            signal_factor = 0.85 + max(0.0, min(1.0, signal)) * 0.45

        return support_factor * trust_factor * status_factor * connect_type_factor * signal_factor
