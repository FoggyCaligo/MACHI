"""TempThoughtGraph — Think 루프 동안 메모리 상에서만 존재하는 임시 사고 그래프.

세계그래프(WorldGraph)의 국소 서브그래프를 복사해 구성하며,
노드/엣지 조작이 자유롭게 일어나되 WorldGraph에 즉시 영향을 주지 않는다.
Think가 끝나면 변경된 내용 중 필요한 부분만 WorldGraph로 커밋한다.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..entities.node import Node
from ..entities.edge import Edge
from ..entities.translated_graph import (
    TranslatedGraph, ConceptPointer, EmptySlot, InputGraphBundle,
)
from ..utils.hash_resolver import ANCHOR_USER
from .graph_patch import GraphPatch


USER_ANCHOR_TEMP_EDGE_WEIGHT = 1.35
GOAL_ANCHOR_TEMP_EDGE_WEIGHT = 0.85
TURN_GOAL_TEMP_EDGE_WEIGHT = 0.95
DEFAULT_ANCHOR_TEMP_EDGE_WEIGHT = 1.0


@dataclass
class GraphDelta:
    """한 루프 회차에서 발생한 변경 사항을 추적한다."""
    added_nodes: list[str] = field(default_factory=list)
    modified_nodes: list[str] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    added_edges: list[str] = field(default_factory=list)
    modified_edges: list[str] = field(default_factory=list)
    removed_edges: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            not self.added_nodes
            and not self.modified_nodes
            and not self.removed_nodes
            and not self.added_edges
            and not self.modified_edges
            and not self.removed_edges
        )


class TempThoughtGraph:
    """임시 사고 그래프.

    Think 루프 1회 실행 단위로 생성된다.
    수렴 판단을 위해 루프 회차별 delta와 GraphPatch를 기록한다.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._adj: dict[str, set[str]] = {}
        self._goal_hash: str | None = None
        self._turn_goal_hash: str | None = None
        self._empty_slots: list[EmptySlot] = []
        self._delta: GraphDelta = GraphDelta()
        self._all_added_nodes: list[str] = []
        self._all_added_edges: list[str] = []
        self._merged_to: dict[str, str] = {}
        self._checked_pairs: set[frozenset[str]] = set()
        self._differentiated_pairs: set[frozenset[str]] = set()
        self._goal_connections: set[str] = set()
        self._loop_index: int = 0
        self._current_patches: list[GraphPatch] = []
        self._all_patches: list[GraphPatch] = []

    # ── 구성 ──────────────────────────────────────────────────────────────────

    def load_from_translated(self, tg: TranslatedGraph) -> None:
        """TranslatedGraph를 TempThoughtGraph에 로드한다."""
        if tg.input_bundle is not None:
            empty_slots = [ref for ref in tg.nodes if isinstance(ref, EmptySlot)]
            self.load_from_input_bundle(tg.input_bundle, empty_slots=empty_slots)
            return

        for ref in tg.nodes:
            if isinstance(ref, ConceptPointer):
                self._load_local_subgraph(ref.local_subgraph)
            elif isinstance(ref, EmptySlot):
                self._empty_slots.append(ref)

    def load_from_input_bundle(
        self,
        bundle: InputGraphBundle,
        *,
        empty_slots: list[EmptySlot] | None = None,
    ) -> None:
        """InputGraphBundle의 국소그래프 묶음을 현재 사고 그래프에 로드한다."""
        for subgraph in bundle.local_subgraphs:
            self._load_local_subgraph(subgraph)

        self._load_turn_goal_from_bundle(bundle)

        if empty_slots is None:
            empty_slots = [EmptySlot(concept_hint=hint) for hint in bundle.empty_hints]
        self._empty_slots.extend(empty_slots)

    def _load_local_subgraph(self, subgraph) -> None:
        for node in subgraph.nodes:
            self._nodes.setdefault(node.address_hash, node)
        for edge in subgraph.edges:
            if edge.edge_id not in self._edges:
                self._edges[edge.edge_id] = edge
                self._adj.setdefault(edge.source_hash, set()).add(edge.target_hash)
                self._adj.setdefault(edge.target_hash, set()).add(edge.source_hash)

    def _load_turn_goal_from_bundle(self, bundle: InputGraphBundle) -> None:
        """현재 입력 bundle에서 이번 턴 목적 node와 임시 목적 연결을 만든다."""
        turn_goal_hash = _turn_goal_hash(bundle.source)
        self._turn_goal_hash = turn_goal_hash
        now = datetime.now(timezone.utc)
        if turn_goal_hash not in self._nodes:
            self._nodes[turn_goal_hash] = Node(
                address_hash=turn_goal_hash,
                node_kind="goal",
                formation_source="runtime",
                labels=["TurnGoal", "이번 턴 목적"],
                is_abstract=False,
                trust_score=1.0,
                stability_score=0.2,
                is_active=True,
                embedding=None,
                payload={
                    "runtime_view": True,
                    "goal_scope": "turn",
                    "source": bundle.source,
                },
                created_at=now,
                updated_at=now,
            )
            self._record_patch(GraphPatch(
                op="add",
                target_kind="node",
                target_id=turn_goal_hash,
                after={"node_kind": "goal", "formation_source": "runtime"},
                reason="turn_goal_from_input_bundle",
                loop_index=self._loop_index,
            ))

        if self._goal_hash is not None:
            self._add_temporary_edge(self._goal_hash, turn_goal_hash, weight=GOAL_ANCHOR_TEMP_EDGE_WEIGHT)

        for concept_hash in sorted(bundle.direct_hashes or bundle.center_hashes):
            if concept_hash in self._nodes:
                self._add_temporary_edge(turn_goal_hash, concept_hash, weight=TURN_GOAL_TEMP_EDGE_WEIGHT)

    def _add_temporary_edge(self, source_hash: str, target_hash: str, *, weight: float) -> None:
        conn_key = f"{source_hash}::{target_hash}"
        if conn_key in self._goal_connections:
            return
        self._goal_connections.add(conn_key)
        self.add_edge(Edge(
            edge_id=str(uuid.uuid4()),
            source_hash=source_hash,
            target_hash=target_hash,
            edge_family="relation",
            connect_type="neutral",
            edge_weight=weight,
            provenance_source="runtime_goal_view",
            is_temporary=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))

    def set_goal_node(self, node: Node) -> None:
        """목표 노드를 설정하고 그래프에 추가한다."""
        self._goal_hash = node.address_hash
        self._nodes[node.address_hash] = node

    # ── 노드 조작 ─────────────────────────────────────────────────────────────

    def add_node(self, node: Node) -> None:
        existed = node.address_hash in self._nodes
        self._nodes[node.address_hash] = node
        self._delta.added_nodes.append(node.address_hash)
        self._all_added_nodes.append(node.address_hash)
        self._record_patch(GraphPatch(
            op="update" if existed else "add",
            target_kind="node",
            target_id=node.address_hash,
            after={"node_kind": node.node_kind, "formation_source": node.formation_source},
            reason="add_node",
            loop_index=self._loop_index,
        ))

    def get_node(self, address_hash: str) -> Node | None:
        return self._nodes.get(address_hash)

    def update_node(self, node: Node) -> None:
        before_node = self._nodes.get(node.address_hash)
        before = _node_patch_state(before_node) if before_node is not None else {}
        self._nodes[node.address_hash] = node
        if node.address_hash not in self._delta.modified_nodes:
            self._delta.modified_nodes.append(node.address_hash)
        self._record_patch(GraphPatch(
            op="update",
            target_kind="node",
            target_id=node.address_hash,
            before=before,
            after=_node_patch_state(node),
            reason="update_node",
            loop_index=self._loop_index,
        ))

    def all_nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def merge_nodes(self, from_hash: str, to_hash: str) -> None:
        """from_hash 노드를 to_hash 노드로 병합한다."""
        if from_hash == to_hash:
            return

        edges = self.get_edges_for_node(from_hash)
        for edge in edges:
            if edge.source_hash == from_hash:
                edge.source_hash = to_hash
            if edge.target_hash == from_hash:
                edge.target_hash = to_hash
            self.update_edge(edge)

        self._adj.pop(from_hash, None)

        self._nodes.pop(from_hash, None)
        self._merged_to[from_hash] = to_hash
        if from_hash not in self._delta.removed_nodes:
            self._delta.removed_nodes.append(from_hash)
        self._record_patch(GraphPatch(
            op="merge",
            target_kind="node",
            target_id=from_hash,
            source_hash=from_hash,
            target_hash=to_hash,
            reason="merge_nodes",
            loop_index=self._loop_index,
        ))

    # ── 엣지 조작 ─────────────────────────────────────────────────────────────

    def add_edge(self, edge: Edge) -> None:
        existed = edge.edge_id in self._edges
        self._edges[edge.edge_id] = edge
        self._delta.added_edges.append(edge.edge_id)
        self._all_added_edges.append(edge.edge_id)
        self._adj.setdefault(edge.source_hash, set()).add(edge.target_hash)
        self._adj.setdefault(edge.target_hash, set()).add(edge.source_hash)
        self._record_patch(GraphPatch(
            op="update" if existed else "add",
            target_kind="edge",
            target_id=edge.edge_id,
            source_hash=edge.source_hash,
            target_hash=edge.target_hash,
            after=_edge_patch_state(edge),
            reason="add_edge",
            loop_index=self._loop_index,
        ))

    def update_edge(self, edge: Edge) -> None:
        """엣지 정보를 업데이트하고 인접 인덱스를 갱신한다."""
        before_edge = self._edges.get(edge.edge_id)
        before = _edge_patch_state(before_edge) if before_edge is not None else {}
        self._edges[edge.edge_id] = edge
        if (edge.edge_id not in self._delta.added_edges and
            edge.edge_id not in self._delta.modified_edges):
            self._delta.modified_edges.append(edge.edge_id)

        self._adj.setdefault(edge.source_hash, set()).add(edge.target_hash)
        self._adj.setdefault(edge.target_hash, set()).add(edge.source_hash)
        self._record_patch(GraphPatch(
            op="update",
            target_kind="edge",
            target_id=edge.edge_id,
            source_hash=edge.source_hash,
            target_hash=edge.target_hash,
            before=before,
            after=_edge_patch_state(edge),
            reason="update_edge",
            loop_index=self._loop_index,
        ))

    def remove_edge(self, edge_id: str) -> None:
        edge = self._edges.pop(edge_id, None)
        if edge is None:
            return
        self._delta.removed_edges.append(edge_id)
        def _still_connected(src: str, tgt: str) -> bool:
            return any(
                (e.source_hash == src and e.target_hash == tgt) or
                (e.source_hash == tgt and e.target_hash == src)
                for e in self._edges.values()
            )
        if not _still_connected(edge.source_hash, edge.target_hash):
            self._adj.get(edge.source_hash, set()).discard(edge.target_hash)
            self._adj.get(edge.target_hash, set()).discard(edge.source_hash)
        self._record_patch(GraphPatch(
            op="remove",
            target_kind="edge",
            target_id=edge_id,
            source_hash=edge.source_hash,
            target_hash=edge.target_hash,
            before=_edge_patch_state(edge),
            reason="remove_edge",
            loop_index=self._loop_index,
        ))

    def get_edge(self, edge_id: str) -> Edge | None:
        """edge_id로 엣지를 O(1) 조회한다."""
        return self._edges.get(edge_id)

    def get_edges_for_node(self, address_hash: str) -> list[Edge]:
        return [
            e for e in self._edges.values()
            if e.source_hash == address_hash or e.target_hash == address_hash
        ]

    def all_edges(self) -> list[Edge]:
        return list(self._edges.values())

    def merge_duplicate_edges(self) -> None:
        """동일 endpoint/관계 구조의 현재 그래프 edge를 하나로 병합한다.

        병합 기준은 edge_family + connect_type + 방향(source_hash → target_hash)이다.
        임시 edge는 별도 뷰 관계이므로 영구 edge와 섞지 않는다.
        """
        grouped: dict[tuple[str, str, str, str, bool], Edge] = {}
        duplicate_ids: list[str] = []

        for edge in list(self._edges.values()):
            key = (
                edge.source_hash,
                edge.target_hash,
                edge.edge_family,
                edge.connect_type,
                edge.is_temporary,
            )
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = edge
                continue

            before = _edge_patch_state(existing)
            existing.edge_weight += edge.edge_weight
            existing.support_count += edge.support_count + 1
            existing.conflict_count += edge.conflict_count
            existing.contradiction_pressure += edge.contradiction_pressure
            existing.trust_score = max(existing.trust_score, edge.trust_score)
            if existing.translation_confidence is None:
                existing.translation_confidence = edge.translation_confidence
            elif edge.translation_confidence is not None:
                existing.translation_confidence = max(
                    existing.translation_confidence,
                    edge.translation_confidence,
                )
            existing.touch()
            duplicate_ids.append(edge.edge_id)
            if edge.edge_id in self._all_added_edges:
                self._all_added_edges.remove(edge.edge_id)
            if existing.edge_id not in self._delta.modified_edges:
                self._delta.modified_edges.append(existing.edge_id)
            self._record_patch(GraphPatch(
                op="merge",
                target_kind="edge",
                target_id=edge.edge_id,
                source_hash=edge.source_hash,
                target_hash=edge.target_hash,
                before=before,
                after=_edge_patch_state(existing),
                reason="merge_duplicate_edges",
                loop_index=self._loop_index,
            ))

        for edge_id in duplicate_ids:
            self._edges.pop(edge_id, None)
            if edge_id not in self._delta.removed_edges:
                self._delta.removed_edges.append(edge_id)

    # ── 엣지 연결 (목표 노드 ↔ 입력 개념) ───────────────────────────────────

    def connect_to_goal(self, concept_hash: str) -> None:
        """개념 노드를 목표 노드에 임시 연결한다."""
        if self._goal_hash is None:
            return
        self.connect_to_identity(concept_hash, self._goal_hash, edge_id_prefix="goal")

    def connect_to_identity(self, concept_hash: str, identity_hash: str, edge_id_prefix: str = "identity") -> None:
        """개념 노드를 참여자 앵커(사용자/AI/목표) 노드에 임시 연결한다.

        이 edge는 identity claim이 아니라 이번 턴의 관측/활성화 view다.
        사용자 앵커 edge는 일반 co-occurrence보다 강하게, goal edge는 내부 방향성
        보조로만 약하게 둔다. 실제 사용자 정체성은 UserProfile identity_surface에서 누적한다.
        """
        conn_key = f"{identity_hash}::{concept_hash}"
        if conn_key in self._goal_connections:
            return
        self._goal_connections.add(conn_key)

        edge = Edge(
            edge_id=str(uuid.uuid4()),
            source_hash=identity_hash,
            target_hash=concept_hash,
            edge_family="relation",
            connect_type="neutral",
            edge_weight=self._temporary_anchor_weight(identity_hash),
            provenance_source="lang_to_graph",
            is_temporary=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.add_edge(edge)

    def _temporary_anchor_weight(self, identity_hash: str) -> float:
        if identity_hash == ANCHOR_USER:
            return USER_ANCHOR_TEMP_EDGE_WEIGHT
        if identity_hash == self._turn_goal_hash:
            return TURN_GOAL_TEMP_EDGE_WEIGHT
        if identity_hash == self._goal_hash:
            return GOAL_ANCHOR_TEMP_EDGE_WEIGHT
        return DEFAULT_ANCHOR_TEMP_EDGE_WEIGHT

    # ── EmptySlot 관리 ────────────────────────────────────────────────────────

    @property
    def empty_slots(self) -> list[EmptySlot]:
        return list(self._empty_slots)

    def has_empty_slots(self) -> bool:
        return bool(self._empty_slots)

    def fill_slot(self, slot: EmptySlot, node: Node) -> None:
        """EmptySlot을 실제 노드로 채운다."""
        self.add_node(node)
        self._empty_slots = [s for s in self._empty_slots if s is not slot]
        self._record_patch(GraphPatch(
            op="fill_slot",
            target_kind="slot",
            target_id=slot.concept_hint,
            target_hash=node.address_hash,
            before={"concept_hint": slot.concept_hint, "importance": slot.importance},
            after={"node_hash": node.address_hash},
            reason="fill_slot",
            loop_index=self._loop_index,
        ))

    # ── ConceptDifferentiation 쌍 추적 ──────────────────────────────────────

    def is_differentiated(self, hash_a: str, hash_b: str) -> bool:
        """두 노드가 이미 분화된 쌍인지 확인한다."""
        return frozenset({hash_a, hash_b}) in self._differentiated_pairs

    def mark_differentiated(self, hash_a: str, hash_b: str) -> None:
        """두 노드를 분화 완료 쌍으로 기록한다."""
        self._differentiated_pairs.add(frozenset({hash_a, hash_b}))
        self._record_patch(GraphPatch(
            op="update",
            target_kind="pair",
            target_id="::".join(sorted([hash_a, hash_b])),
            source_hash=hash_a,
            target_hash=hash_b,
            after={"differentiated": True},
            reason="mark_differentiated",
            loop_index=self._loop_index,
        ))

    def is_pair_checked(self, hash_a: str, hash_b: str) -> bool:
        """두 노드 쌍이 이미 유사도 검사를 마쳤는지 확인한다."""
        return frozenset({hash_a, hash_b}) in self._checked_pairs

    def mark_pair_checked(self, hash_a: str, hash_b: str) -> None:
        """두 노드 쌍을 검사 완료로 기록한다."""
        self._checked_pairs.add(frozenset({hash_a, hash_b}))
        self._record_patch(GraphPatch(
            op="update",
            target_kind="pair",
            target_id="::".join(sorted([hash_a, hash_b])),
            source_hash=hash_a,
            target_hash=hash_b,
            after={"checked": True},
            reason="mark_pair_checked",
            loop_index=self._loop_index,
        ))

    def reset_pair_checks(self) -> None:
        """검사 이력을 초기화한다 (노드 수정 시 호출)."""
        self._checked_pairs.clear()

    # ── 수렴 판단 ─────────────────────────────────────────────────────────────

    def current_delta(self) -> GraphDelta:
        return self._delta

    def reset_delta(self) -> None:
        """루프 회차 시작 시 delta를 초기화한다. (수렴 판단 전용)

        _all_added_nodes / _all_added_edges / _all_patches는 초기화하지 않는다.
        """
        self._loop_index += 1
        self._delta = GraphDelta()
        self._current_patches = []

    def current_patches(self) -> list[GraphPatch]:
        return list(self._current_patches)

    def all_patches(self) -> list[GraphPatch]:
        return list(self._all_patches)

    def _record_patch(self, patch: GraphPatch) -> None:
        self._current_patches.append(patch)
        self._all_patches.append(patch)

    @property
    def all_added_node_hashes(self) -> list[str]:
        return self._all_added_nodes

    @property
    def all_added_edge_ids(self) -> list[str]:
        return self._all_added_edges

    @property
    def merged_mappings(self) -> dict[str, str]:
        return self._merged_to

    @property
    def turn_goal_hash(self) -> str | None:
        return self._turn_goal_hash

    # ── 읽기 전용 속성 ────────────────────────────────────────────────────────
    @property
    def goal_hash(self) -> str | None:
        return self._goal_hash

    def neighbor_hashes(self, address_hash: str) -> set[str]:
        return set(self._adj.get(address_hash, set()))


def _turn_goal_hash(source: str) -> str:
    return hashlib.sha256(f"turn-goal::{source}".encode("utf-8")).hexdigest()[:32]


def _node_patch_state(node: Node | None) -> dict:
    if node is None:
        return {}
    return {
        "node_kind": node.node_kind,
        "trust_score": node.trust_score,
        "stability_score": node.stability_score,
        "is_active": node.is_active,
    }


def _edge_patch_state(edge: Edge | None) -> dict:
    if edge is None:
        return {}
    return {
        "edge_family": edge.edge_family,
        "connect_type": edge.connect_type,
        "edge_weight": edge.edge_weight,
        "support_count": edge.support_count,
        "is_temporary": edge.is_temporary,
    }
