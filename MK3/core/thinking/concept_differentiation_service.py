from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from core.entities.conclusion import ContradictionSignal
from core.entities.edge import Edge
from core.entities.graph_event import GraphEvent
from core.entities.thought_view import ThoughtView
from storage.unit_of_work import UnitOfWork


@dataclass(slots=True)
class DifferentiationAction:
    action: str          # 'created_concept_edge' | 'reinforced_concept_edge'
    edge_id: int
    from_node_id: int
    to_node_id: int
    connect_type: str    # 'flow' | 'neutral' | 'conflict'
    inferred_from: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DifferentiationResult:
    actions: list[DifferentiationAction] = field(default_factory=list)

    @property
    def created_edge_ids(self) -> list[int]:
        return [a.edge_id for a in self.actions if a.action == 'created_concept_edge']

    @property
    def reinforced_edge_ids(self) -> list[int]:
        return [a.edge_id for a in self.actions if a.action == 'reinforced_concept_edge']

    def to_metadata(self) -> dict[str, Any]:
        return {
            'created_concept_edge_count': len(self.created_edge_ids),
            'reinforced_concept_edge_count': len(self.reinforced_edge_ids),
            'actions': [
                {
                    'action': a.action,
                    'edge_id': a.edge_id,
                    'from_node_id': a.from_node_id,
                    'to_node_id': a.to_node_id,
                    'connect_type': a.connect_type,
                    'inferred_from': a.inferred_from,
                }
                for a in self.actions
            ],
        }


@dataclass(slots=True)
class ConceptDifferentiationService:
    """Detect and materialize concept hierarchy and same-kind relationships.

    Design principles (철학 유지):
    - 문자열 휴리스틱 없음. 모든 신호는 그래프 구조에서만 옵니다.
    - partial_reuse 포인터 누적 → 개념 계층 증거 → concept/flow 엣지
    - 공유 co-occurrence 이웃 → 동종 증거 → concept/neutral 엣지
    - 임계치는 보수적으로. 반복된 구조 증거가 쌓일 때만 엣지를 생성합니다.

    Edge semantics:
      concept/flow    : from → to 방향으로 구체화 (from이 더 추상적인 상위 개념)
      concept/neutral : 같은 수준의 동종 관계 (별칭, 동류)
      concept/conflict: 개념 수준 충돌 (향후 확장)
    """

    hierarchy_pointer_threshold: int = 2
    same_kind_shared_neighbor_min: int = 3
    same_kind_ratio_threshold: float = 0.50
    initial_concept_trust: float = 0.52
    reinforce_trust_delta: float = 0.015
    concept_conflict_score_threshold: float = 0.75  # ContradictionDetector 'high' 기준과 동기

    def differentiate(
        self,
        uow: UnitOfWork,
        *,
        thought_view: ThoughtView,
        message_id: int | None = None,
        contradiction_signals: list[ContradictionSignal] | None = None,
    ) -> DifferentiationResult:
        result = DifferentiationResult()
        self._detect_hierarchy(uow, thought_view=thought_view, message_id=message_id, result=result)
        self._detect_same_kind(uow, thought_view=thought_view, message_id=message_id, result=result)
        if contradiction_signals:
            self._detect_concept_conflict(
                uow,
                contradiction_signals=contradiction_signals,
                message_id=message_id,
                result=result,
            )
        return result

    # ── Signal 1: partial_reuse 포인터 누적 → concept/flow (계층) ─────────────

    def _detect_hierarchy(
        self,
        uow: UnitOfWork,
        *,
        thought_view: ThoughtView,
        message_id: int | None,
        result: DifferentiationResult,
    ) -> None:
        # partial_reuse: owner_node (longer/specific) contains referenced_node (shorter/abstract)
        # concept/flow goes abstract → specific, so: referenced → owner
        pair_counts: dict[tuple[int, int], int] = defaultdict(int)
        for pointer in thought_view.pointers:
            if pointer.pointer_type != 'partial_reuse':
                continue
            owner_id = pointer.owner_node_id
            ref_id = pointer.referenced_node_id
            if owner_id and ref_id and owner_id != ref_id:
                pair_counts[(ref_id, owner_id)] += 1  # abstract → specific

        for (abstract_id, specific_id), count in pair_counts.items():
            if count < self.hierarchy_pointer_threshold:
                continue
            self._ensure_concept_edge(
                uow,
                from_node_id=abstract_id,
                to_node_id=specific_id,
                connect_type='flow',
                relation_detail={
                    'inferred_from': 'partial_reuse_accumulation',
                    'pointer_count': count,
                    'note': (
                        'Hierarchical relationship inferred from repeated textual '
                        'containment evidence. The target concept is a more specific '
                        'form of the source concept.'
                    ),
                },
                message_id=message_id,
                result=result,
            )

    # ── Signal 2: 공유 co-occurrence 이웃 → concept/neutral (동종) ───────────

    def _detect_same_kind(
        self,
        uow: UnitOfWork,
        *,
        thought_view: ThoughtView,
        message_id: int | None,
        result: DifferentiationResult,
    ) -> None:
        # Build co-occurrence neighbor map (relation/neutral edges only)
        neighbor_map: dict[int, set[int]] = defaultdict(set)
        for edge in thought_view.edges:
            if edge.edge_family != 'relation' or edge.connect_type != 'neutral':
                continue
            if not edge.is_active:
                continue
            if edge.source_node_id and edge.target_node_id:
                neighbor_map[edge.source_node_id].add(edge.target_node_id)
                neighbor_map[edge.target_node_id].add(edge.source_node_id)

        # Containment pairs (skip these — they belong to hierarchy, not same-kind)
        containment_pairs: set[tuple[int, int]] = set()
        for pointer in thought_view.pointers:
            if pointer.pointer_type != 'partial_reuse':
                continue
            o, r = pointer.owner_node_id, pointer.referenced_node_id
            if o and r:
                containment_pairs.add((o, r))
                containment_pairs.add((r, o))

        node_ids = [n.id for n in thought_view.nodes if n.id is not None]

        for i, id_a in enumerate(node_ids):
            for id_b in node_ids[i + 1:]:
                if id_a == id_b:
                    continue
                # Skip if containment relationship exists
                if (id_a, id_b) in containment_pairs:
                    continue

                neighbors_a = neighbor_map.get(id_a, set())
                neighbors_b = neighbor_map.get(id_b, set())
                shared = neighbors_a & neighbors_b

                if len(shared) < self.same_kind_shared_neighbor_min:
                    continue
                union = neighbors_a | neighbors_b
                if not union:
                    continue
                ratio = len(shared) / len(union)
                if ratio < self.same_kind_ratio_threshold:
                    continue

                self._ensure_concept_edge(
                    uow,
                    from_node_id=id_a,
                    to_node_id=id_b,
                    connect_type='neutral',
                    relation_detail={
                        'inferred_from': 'shared_cooccurrence_neighbors',
                        'shared_neighbor_count': len(shared),
                        'overlap_ratio': round(ratio, 4),
                        'note': (
                            'Same-kind relationship inferred from shared co-occurrence '
                            'neighborhood. Both concepts frequently appear with the same '
                            'surrounding concepts.'
                        ),
                    },
                    message_id=message_id,
                    result=result,
                )

    # ── Signal 3: 고강도 ContradictionSignal → concept/conflict (개념 충돌) ────

    def _detect_concept_conflict(
        self,
        uow: UnitOfWork,
        *,
        contradiction_signals: list[ContradictionSignal],
        message_id: int | None,
        result: DifferentiationResult,
    ) -> None:
        """High-severity contradiction signals are evidence of concept-level conflict.

        When an edge between two nodes has accumulated enough contradiction
        pressure (score >= concept_conflict_score_threshold), we record a
        concept/conflict edge between the two concept nodes themselves.
        This edge is distinct from the underlying relation edge — it represents
        the inferred structural incompatibility at the concept level.
        """
        seen_pairs: set[tuple[int, int]] = set()
        for signal in contradiction_signals:
            if signal.score < self.concept_conflict_score_threshold:
                continue
            from_id = signal.source_node_id
            to_id = signal.target_node_id
            if not from_id or not to_id or from_id == to_id:
                continue
            # Canonicalise pair so (A, B) and (B, A) don't produce two edges
            pair = (min(from_id, to_id), max(from_id, to_id))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            self._ensure_concept_edge(
                uow,
                from_node_id=from_id,
                to_node_id=to_id,
                connect_type='conflict',
                relation_detail={
                    'inferred_from': 'high_severity_contradiction_signal',
                    'signal_score': signal.score,
                    'signal_reason': signal.reason,
                    'triggering_edge_id': signal.edge_id,
                    'note': (
                        'Concept-level conflict inferred from high-severity structural '
                        'contradiction. The two nodes are in fundamental opposition '
                        'according to current graph evidence.'
                    ),
                },
                message_id=message_id,
                result=result,
            )

    # ── 공통: concept 엣지 생성 또는 강화 ──────────────────────────────────────

    def _ensure_concept_edge(
        self,
        uow: UnitOfWork,
        *,
        from_node_id: int,
        to_node_id: int,
        connect_type: str,
        relation_detail: dict[str, Any],
        message_id: int | None,
        result: DifferentiationResult,
    ) -> None:
        existing = uow.edges.find_active_relation(
            from_node_id,
            to_node_id,
            edge_family='concept',
            connect_type=connect_type,
        )
        if existing is not None and existing.id is not None:
            uow.edges.bump_support(existing.id, delta=1, trust_delta=self.reinforce_trust_delta)
            result.actions.append(DifferentiationAction(
                action='reinforced_concept_edge',
                edge_id=existing.id,
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                connect_type=connect_type,
                inferred_from=str(relation_detail.get('inferred_from', '')),
            ))
            return

        event = uow.graph_events.add(GraphEvent(
            event_uid=f'evt-{uuid4().hex}',
            event_type='concept_edge_created',
            message_id=message_id,
            parsed_input={
                'from_node_id': from_node_id,
                'to_node_id': to_node_id,
                'connect_type': connect_type,
                'inferred_from': relation_detail.get('inferred_from'),
            },
            effect={
                'edge_family': 'concept',
                'connect_type': connect_type,
                'initial_trust': self.initial_concept_trust,
            },
            note=str(relation_detail.get('note', '')),
        ))

        new_edge = uow.edges.add(Edge(
            edge_uid=f'concept-{uuid4().hex}',
            source_node_id=from_node_id,
            target_node_id=to_node_id,
            edge_family='concept',
            connect_type=connect_type,
            relation_detail=relation_detail,
            edge_weight=0.30,
            trust_score=self.initial_concept_trust,
            support_count=1,
            created_from_event_id=event.id,
        ))

        if new_edge.id is not None:
            result.actions.append(DifferentiationAction(
                action='created_concept_edge',
                edge_id=new_edge.id,
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                connect_type=connect_type,
                inferred_from=str(relation_detail.get('inferred_from', '')),
                metadata={
                    'shared_neighbor_count': relation_detail.get('shared_neighbor_count'),
                    'pointer_count': relation_detail.get('pointer_count'),
                    'overlap_ratio': relation_detail.get('overlap_ratio'),
                },
            ))
