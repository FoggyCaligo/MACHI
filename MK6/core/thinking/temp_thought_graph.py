"""TempThoughtGraph — Think 루프 동안 메모리 상에서만 존재하는 임시 사고 그래프.

세계그래프(WorldGraph)의 국소 서브그래프를 복사해 구성하며,
노드/엣지 조작이 자유롭게 일어나되 WorldGraph에 즉시 영향을 주지 않는다.
Think가 끝나면 변경된 내용 중 필요한 부분만 WorldGraph로 커밋한다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..entities.node import Node
from ..entities.edge import Edge
from ..entities.translated_graph import (
    TranslatedGraph, ConceptPointer, EmptySlot,
)


@dataclass
class GraphDelta:
    """한 루프 회차에서 발생한 변경 사항을 추적한다."""
    added_nodes: list[str] = field(default_factory=list)    # address_hash
    modified_nodes: list[str] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    added_edges: list[str] = field(default_factory=list)    # edge_id
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
    수렴 판단을 위해 루프 회차별 delta를 기록한다.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}
        self._adj: dict[str, set[str]] = {}      # address_hash → 이웃 hash 집합 (O(1) 조회)
        self._goal_hash: str | None = None       # 목표 노드 address_hash
        self._empty_slots: list[EmptySlot] = []  # 아직 채워지지 않은 자리
        self._delta: GraphDelta = GraphDelta()   # 현재 루프 회차 변경 추적 (수렴 판단용)
        self._all_added_nodes: list[str] = []    # 루프 전체 누적 추가 노드 (커밋용)
        self._all_added_edges: list[str] = []    # 루프 전체 누적 추가 엣지 (커밋용)
        self._merged_to: dict[str, str] = {}     # address_hash → 본체 hash (병합 추적)
        self._checked_pairs: set[frozenset[str]] = set() # 이번 사고 턴에서 검증 완료한 쌍
        self._differentiated_pairs: set[frozenset[str]] = set()  # 이미 분화한 쌍 기록
        self._goal_connections: set[str] = set()  # 목표 노드에 연결된 개념 hash 집합 (중복 방지)

    # ── 구성 ──────────────────────────────────────────────────────────────────

    def load_from_translated(self, tg: TranslatedGraph) -> None:
        """TranslatedGraph에서 ConceptPointer들의 국소 서브그래프를 로드한다."""
        for ref in tg.nodes:
            if isinstance(ref, ConceptPointer):
                subgraph = ref.local_subgraph
                for node in subgraph.nodes:
                    self._nodes.setdefault(node.address_hash, node)
                for edge in subgraph.edges:
                    if edge.edge_id not in self._edges:
                        self._edges[edge.edge_id] = edge
                        self._adj.setdefault(edge.source_hash, set()).add(edge.target_hash)
                        self._adj.setdefault(edge.target_hash, set()).add(edge.source_hash)
            elif isinstance(ref, EmptySlot):
                self._empty_slots.append(ref)

    def set_goal_node(self, node: Node) -> None:
        """목표 노드를 설정하고 그래프에 추가한다."""
        self._goal_hash = node.address_hash
        self._nodes[node.address_hash] = node

    # ── 노드 조작 ─────────────────────────────────────────────────────────────

    def add_node(self, node: Node) -> None:
        self._nodes[node.address_hash] = node
        self._delta.added_nodes.append(node.address_hash)
        self._all_added_nodes.append(node.address_hash)

    def get_node(self, address_hash: str) -> Node | None:
        return self._nodes.get(address_hash)

    def update_node(self, node: Node) -> None:
        self._nodes[node.address_hash] = node
        if node.address_hash not in self._delta.modified_nodes:
            self._delta.modified_nodes.append(node.address_hash)

    def all_nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def merge_nodes(self, from_hash: str, to_hash: str) -> None:
        """from_hash 노드를 to_hash 노드로 병합한다."""
        if from_hash == to_hash:
            return

        # 1. 엣지 재연결
        edges = self.get_edges_for_node(from_hash)
        for edge in edges:
            if edge.source_hash == from_hash:
                edge.source_hash = to_hash
            if edge.target_hash == from_hash:
                edge.target_hash = to_hash
            self.update_edge(edge)

        # 2. 인접 인덱스 정리
        self._adj.pop(from_hash, None)
        # to_hash의 이웃은 update_edge 로직에서 자연스럽게 보강됨

        # 3. 노드 제거 및 기록
        self._nodes.pop(from_hash, None)
        self._merged_to[from_hash] = to_hash
        if from_hash not in self._delta.removed_nodes:
            self._delta.removed_nodes.append(from_hash)

    # ── 엣지 조작 ─────────────────────────────────────────────────────────────

    def add_edge(self, edge: Edge) -> None:
        self._edges[edge.edge_id] = edge
        self._delta.added_edges.append(edge.edge_id)
        self._all_added_edges.append(edge.edge_id)
        # 인접 인덱스 업데이트
        self._adj.setdefault(edge.source_hash, set()).add(edge.target_hash)
        self._adj.setdefault(edge.target_hash, set()).add(edge.source_hash)

    def update_edge(self, edge: Edge) -> None:
        """엣지 정보를 업데이트하고 인접 인덱스를 갱신한다."""
        self._edges[edge.edge_id] = edge
        if (edge.edge_id not in self._delta.added_edges and 
            edge.edge_id not in self._delta.modified_edges):
            self._delta.modified_edges.append(edge.edge_id)
        
        # 인접 인덱스 최신화
        self._adj.setdefault(edge.source_hash, set()).add(edge.target_hash)
        self._adj.setdefault(edge.target_hash, set()).add(edge.source_hash)

    def remove_edge(self, edge_id: str) -> None:
        edge = self._edges.pop(edge_id, None)
        if edge is None:
            return
        self._delta.removed_edges.append(edge_id)
        # 인접 인덱스에서 해당 방향 제거 (다른 엣지로 여전히 연결돼 있을 수 있으므로 잔존 확인)
        def _still_connected(src: str, tgt: str) -> bool:
            return any(
                (e.source_hash == src and e.target_hash == tgt) or
                (e.source_hash == tgt and e.target_hash == src)
                for e in self._edges.values()
            )
        if not _still_connected(edge.source_hash, edge.target_hash):
            self._adj.get(edge.source_hash, set()).discard(edge.target_hash)
            self._adj.get(edge.target_hash, set()).discard(edge.source_hash)

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

    # ── 엣지 연결 (목표 노드 ↔ 입력 개념) ───────────────────────────────────

    def connect_to_goal(self, concept_hash: str) -> None:
        """개념 노드를 목표 노드에 임시 연결한다.

        같은 concept_hash가 이미 연결돼 있으면 중복 엣지를 생성하지 않는다.
        """
        if self._goal_hash is None:
            return
        if concept_hash in self._goal_connections:
            return
        self._goal_connections.add(concept_hash)
        edge = Edge(
            edge_id=str(uuid.uuid4()),
            source_hash=self._goal_hash,
            target_hash=concept_hash,
            edge_family="relation",
            connect_type="neutral",
            provenance_source="lang_to_graph",
            is_temporary=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.add_edge(edge)

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

    # ── ConceptDifferentiation 쌍 추적 ──────────────────────────────────────

    def is_differentiated(self, hash_a: str, hash_b: str) -> bool:
        """두 노드가 이미 분화된 쌍인지 확인한다."""
        return frozenset({hash_a, hash_b}) in self._differentiated_pairs

    def mark_differentiated(self, hash_a: str, hash_b: str) -> None:
        """두 노드를 분화 완료 쌍으로 기록한다."""
        self._differentiated_pairs.add(frozenset({hash_a, hash_b}))

    def is_pair_checked(self, hash_a: str, hash_b: str) -> bool:
        """두 노드 쌍이 이미 유사도 검사를 마쳤는지 확인한다."""
        return frozenset({hash_a, hash_b}) in self._checked_pairs

    def mark_pair_checked(self, hash_a: str, hash_b: str) -> None:
        """두 노드 쌍을 검사 완료로 기록한다."""
        self._checked_pairs.add(frozenset({hash_a, hash_b}))

    def reset_pair_checks(self) -> None:
        """검사 이력을 초기화한다 (노드 수정 시 호출)."""
        self._checked_pairs.clear()

    # ── 수렴 판단 ─────────────────────────────────────────────────────────────

    def current_delta(self) -> GraphDelta:
        return self._delta

    def reset_delta(self) -> None:
        """루프 회차 시작 시 delta를 초기화한다. (수렴 판단 전용)

        _all_added_nodes / _all_added_edges는 초기화하지 않는다.
        커밋 추적은 루프 전체에 걸쳐 누적된다.
        """
        self._delta = GraphDelta()

    @property
    def all_added_node_hashes(self) -> list[str]:
        """루프 전체에 걸쳐 add_node()로 추가된 노드의 address_hash 목록 (커밋용)."""
        return self._all_added_nodes

    @property
    def all_added_edge_ids(self) -> list[str]:
        """루프 전체에 걸쳐 add_edge()로 추가된 엣지의 edge_id 목록 (커밋용)."""
        return self._all_added_edges

    @property
    def merged_mappings(self) -> dict[str, str]:
        """루프 전체에 걸쳐 발생한 노드 병합 매핑 (from_hash -> to_hash)."""
        return self._merged_to

    # ── 읽기 전용 속성 ────────────────────────────────────────────────────────
    @property
    def goal_hash(self) -> str | None:
        return self._goal_hash

    def neighbor_hashes(self, address_hash: str) -> set[str]:
        """노드의 이웃 노드 hash 집합을 O(1)로 반환한다."""
        return set(self._adj.get(address_hash, set()))
