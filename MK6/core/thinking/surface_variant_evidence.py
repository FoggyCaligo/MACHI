"""SurfaceVariantEvidence — 표면형 차이를 병합 근거 edge로 축적한다.

이 모듈은 문자열 포함/접미사/이름 규칙으로 surface를 분해하지 않는다.
현재 활성화된 그래프 안에서 embedding 유사도와 공유 이웃이 충분한 노드 쌍만
보수적인 병합 후보 근거로 연결한다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations

from ... import config
from ..entities.edge import Edge
from ..entities.node import Node
from .concept_differentiation import composite_score
from .temp_thought_graph import TempThoughtGraph


SURFACE_VARIANT_SCORE_THRESHOLD = 0.94
SURFACE_VARIANT_MIN_SHARED_NEIGHBORS = 1
SURFACE_VARIANT_EDGE_WEIGHT = 0.35
SURFACE_VARIANT_TRUST_SCORE = 0.45


@dataclass(frozen=True, slots=True)
class SurfaceVariantEvidence:
    source_hash: str
    target_hash: str
    score: float
    shared_neighbor_count: int


def run(tg: TempThoughtGraph) -> list[SurfaceVariantEvidence]:
    """현재 사고 그래프에서 surface variant 후보 근거 edge를 누적한다.

    후보 조건은 문자열 형태가 아니라 구조 신호다.
    - 두 노드 모두 embedding을 가진 활성 concept이어야 한다.
    - 추상 노드와 goal node는 제외한다.
    - composite score가 충분히 높아야 한다.
    - 공유 이웃이 최소 1개 이상 있어야 한다.

    이 단계는 merge를 직접 수행하지 않는다. 중립 concept edge/support를 누적해
    ConceptMerge가 이후 안정성, 직접 지지, 공유 이웃 조건으로 병합 여부를 판단한다.
    """
    nodes = [
        n for n in tg.all_nodes()
        if n.embedding is not None
        and n.is_active
        and not n.is_abstract
        and n.address_hash != tg.goal_hash
    ]
    if len(nodes) < 2:
        return []

    neighbor_cache = {
        n.address_hash: tg.neighbor_hashes(n.address_hash)
        for n in nodes
    }

    results: list[SurfaceVariantEvidence] = []
    for node_a, node_b in combinations(nodes, 2):
        hash_a, hash_b = node_a.address_hash, node_b.address_hash
        if tg.get_node(hash_a) is None or tg.get_node(hash_b) is None:
            continue

        neighbors_a = neighbor_cache[hash_a]
        neighbors_b = neighbor_cache[hash_b]
        shared_neighbors = (neighbors_a & neighbors_b) - {hash_a, hash_b}
        if len(shared_neighbors) < SURFACE_VARIANT_MIN_SHARED_NEIGHBORS:
            continue

        score = composite_score(node_a, node_b, neighbors_a, neighbors_b)
        if score < SURFACE_VARIANT_SCORE_THRESHOLD:
            continue

        if _has_existing_support_edge(tg, hash_a, hash_b):
            continue

        edge = _make_support_edge(
            node_a,
            node_b,
            score=score,
            shared_neighbor_count=len(shared_neighbors),
        )
        tg.add_edge(edge)
        results.append(SurfaceVariantEvidence(
            source_hash=hash_a,
            target_hash=hash_b,
            score=score,
            shared_neighbor_count=len(shared_neighbors),
        ))

    return results


def _has_existing_support_edge(tg: TempThoughtGraph, hash_a: str, hash_b: str) -> bool:
    for edge in tg.get_edges_for_node(hash_a):
        if {edge.source_hash, edge.target_hash} != {hash_a, hash_b}:
            continue
        if edge.is_temporary:
            continue
        if edge.connect_type == "conflict":
            continue
        if edge.proposed_connect_type == "surface_variant_evidence":
            return True
    return False


def _make_support_edge(
    node_a: Node,
    node_b: Node,
    *,
    score: float,
    shared_neighbor_count: int,
) -> Edge:
    now = datetime.now(timezone.utc)
    return Edge(
        edge_id=str(uuid.uuid4()),
        source_hash=node_a.address_hash,
        target_hash=node_b.address_hash,
        edge_family="concept",
        connect_type="neutral",
        edge_weight=SURFACE_VARIANT_EDGE_WEIGHT,
        trust_score=SURFACE_VARIANT_TRUST_SCORE,
        support_count=1,
        provenance_source="differentiation",
        proposed_connect_type="surface_variant_evidence",
        proposal_reason="embedding/shared-neighbor evidence for possible surface variant merge",
        payload={
            "composite_score": score,
            "shared_neighbor_count": shared_neighbor_count,
        },
        is_temporary=False,
        created_at=now,
        updated_at=now,
    )
