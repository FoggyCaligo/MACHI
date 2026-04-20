"""LocalGraphExtractor — 노드 중심 N-hop 국소 그래프 추출."""
from __future__ import annotations

import sqlite3
from collections import deque

from ..entities.node import Node
from ..entities.edge import Edge
from ..entities.translated_graph import LocalSubgraph
from ..storage.world_graph import get_node, get_edges_for_node
from ... import config


def extract(
    conn: sqlite3.Connection,
    center_hash: str,
    *,
    hop_radius: int | None = None,
    trust_threshold: float | None = None,
) -> LocalSubgraph:
    """center_hash 노드를 중심으로 N-hop 이내의 국소 그래프를 반환한다.

    Args:
        conn:            DB 커넥션
        center_hash:     중심 노드의 address_hash
        hop_radius:      탐색 반경 (기본값: config.LOCAL_GRAPH_N_HOP)
        trust_threshold: 이 값 미만의 trust_score를 가진 노드는 포함하지 않음
                         (기본값: config.LOCAL_GRAPH_TRUST_THRESHOLD)

    Returns:
        LocalSubgraph — 중심 노드 포함, 발견된 노드·엣지 전체
    """
    n_hop = hop_radius if hop_radius is not None else config.LOCAL_GRAPH_N_HOP
    min_trust = (
        trust_threshold
        if trust_threshold is not None
        else config.LOCAL_GRAPH_TRUST_THRESHOLD
    )

    visited_nodes: dict[str, Node] = {}
    visited_edges: dict[str, Edge] = {}

    # BFS
    queue: deque[tuple[str, int]] = deque()
    queue.append((center_hash, 0))
    queued: set[str] = {center_hash}

    while queue:
        current_hash, depth = queue.popleft()

        node = get_node(conn, current_hash)
        if node is None or not node.is_active:
            continue

        # center 노드(depth=0)는 trust threshold와 무관하게 항상 포함한다.
        # 이웃 노드(depth>0)만 trust threshold로 필터링한다.
        if depth > 0 and node.trust_score < min_trust:
            continue

        visited_nodes[current_hash] = node

        if depth >= n_hop:
            continue

        edges = get_edges_for_node(conn, current_hash, active_only=True)
        for edge in edges:
            if edge.edge_id in visited_edges:
                continue
            visited_edges[edge.edge_id] = edge

            neighbor_hash = (
                edge.target_hash
                if edge.source_hash == current_hash
                else edge.source_hash
            )
            if neighbor_hash not in queued:
                queued.add(neighbor_hash)
                queue.append((neighbor_hash, depth + 1))

    return LocalSubgraph(
        center_hash=center_hash,
        nodes=list(visited_nodes.values()),
        edges=list(visited_edges.values()),
        hop_radius=n_hop,
    )
