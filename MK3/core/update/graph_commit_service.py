from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from core.entities.graph_event import GraphEvent
from core.update.edge_update_service import EdgeUpdateService
from core.update.node_merge_service import NodeMergeRequest, NodeMergeResult, NodeMergeService
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class EdgeSupportRequest:
    edge_id: int
    delta: int = 1
    trust_delta: float | None = None


@dataclass(slots=True)
class EdgeConflictRequest:
    edge_id: int
    delta: int = 1
    pressure_delta: float | None = None
    trust_delta: float | None = None


@dataclass(slots=True)
class GraphMutationPlan:
    """Declarative description of a batch graph change.

    Operations are applied in a single UnitOfWork in the following order:
        1. support_requests   — reinforce edges
        2. conflict_requests  — apply conflict pressure (may auto-flag revision)
        3. auto-deactivation  — any modified edge whose trust fell below threshold
        4. deactivation_edge_ids — explicit deactivations (skipped if already auto-deactivated)
        5. node_merges        — structural node absorption

    A single graph_commit event is recorded after all mutations succeed.
    """

    reason: str
    message_id: int | None = None
    note: str | None = None
    support_requests: list[EdgeSupportRequest] = field(default_factory=list)
    conflict_requests: list[EdgeConflictRequest] = field(default_factory=list)
    deactivation_edge_ids: list[int] = field(default_factory=list)
    node_merges: list[NodeMergeRequest] = field(default_factory=list)


@dataclass(slots=True)
class GraphCommitResult:
    plan_reason: str
    commit_event_id: int | None = None
    supported_edge_ids: list[int] = field(default_factory=list)
    conflicted_edge_ids: list[int] = field(default_factory=list)
    deactivated_edge_ids: list[int] = field(default_factory=list)
    auto_deactivated_edge_ids: list[int] = field(default_factory=list)
    node_merge_results: list[NodeMergeResult] = field(default_factory=list)
    created_event_ids: list[int] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            'plan_reason': self.plan_reason,
            'commit_event_id': self.commit_event_id,
            'supported_edge_count': len(self.supported_edge_ids),
            'conflicted_edge_count': len(self.conflicted_edge_ids),
            'deactivated_edge_count': len(self.deactivated_edge_ids),
            'auto_deactivated_edge_count': len(self.auto_deactivated_edge_ids),
            'node_merge_count': len(self.node_merge_results),
        }


class GraphCommitService:
    """Atomic orchestrator for structural graph mutations.

    Wraps EdgeUpdateService and NodeMergeService so that support bumps,
    conflict pressure, explicit deactivations, and node merges all land in
    a single UnitOfWork transaction.

    Design principle: no semantic interpretation. Callers decide what the
    mutations mean; this service only guarantees ordering and atomicity.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        *,
        edge_update_service: EdgeUpdateService | None = None,
        node_merge_service: NodeMergeService | None = None,
    ) -> None:
        self.uow_factory = uow_factory
        self.edge_update_service = edge_update_service or EdgeUpdateService()
        self.node_merge_service = node_merge_service or NodeMergeService(uow_factory)

    def commit(self, plan: GraphMutationPlan) -> GraphCommitResult:
        result = GraphCommitResult(plan_reason=plan.reason)

        with self.uow_factory() as uow:
            # ── 1. Support ──────────────────────────────────────────────────
            for req in plan.support_requests:
                self.edge_update_service.apply_support(
                    uow,
                    req.edge_id,
                    message_id=plan.message_id,
                    delta=req.delta,
                    trust_delta=req.trust_delta,
                )
                result.supported_edge_ids.append(req.edge_id)

            # ── 2. Conflict ─────────────────────────────────────────────────
            for req in plan.conflict_requests:
                self.edge_update_service.apply_conflict(
                    uow,
                    req.edge_id,
                    message_id=plan.message_id,
                    delta=req.delta,
                    pressure_delta=req.pressure_delta,
                    trust_delta=req.trust_delta,
                )
                result.conflicted_edge_ids.append(req.edge_id)

            # ── 3. Auto-deactivate edges that fell below trust threshold ────
            all_modified = list(dict.fromkeys(
                result.supported_edge_ids + result.conflicted_edge_ids
            ))
            for edge_id in all_modified:
                deactivated = self.edge_update_service.deactivate_if_below_threshold(
                    uow, edge_id, message_id=plan.message_id,
                )
                if deactivated:
                    result.auto_deactivated_edge_ids.append(edge_id)

            # ── 4. Explicit deactivations (skip already auto-deactivated) ──
            auto_set = set(result.auto_deactivated_edge_ids)
            for edge_id in plan.deactivation_edge_ids:
                if edge_id in auto_set:
                    continue
                self.edge_update_service.deactivate(
                    uow,
                    edge_id,
                    message_id=plan.message_id,
                    reason=plan.reason,
                )
                result.deactivated_edge_ids.append(edge_id)

            # ── 5. Node merges (same UoW, no nested commit) ─────────────────
            for merge_req in plan.node_merges:
                merge_result = self.node_merge_service.merge_with_uow(uow, merge_req)
                result.node_merge_results.append(merge_result)

            # ── 6. Batch commit event ────────────────────────────────────────
            commit_event = uow.graph_events.add(GraphEvent(
                event_uid=f'evt-{uuid4().hex}',
                event_type='graph_commit',
                message_id=plan.message_id,
                parsed_input={
                    'reason': plan.reason,
                    'support_count': len(result.supported_edge_ids),
                    'conflict_count': len(result.conflicted_edge_ids),
                    'explicit_deactivation_count': len(result.deactivated_edge_ids),
                    'auto_deactivation_count': len(result.auto_deactivated_edge_ids),
                    'node_merge_count': len(result.node_merge_results),
                },
                effect={
                    'supported_edge_ids': result.supported_edge_ids,
                    'conflicted_edge_ids': result.conflicted_edge_ids,
                    'deactivated_edge_ids': result.deactivated_edge_ids,
                    'auto_deactivated_edge_ids': result.auto_deactivated_edge_ids,
                },
                note=plan.note or plan.reason,
            ))
            result.commit_event_id = commit_event.id
            result.created_event_ids.append(commit_event.id or 0)

            uow.commit()

        return result
