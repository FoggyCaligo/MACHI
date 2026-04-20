"""ConceptDifferentiation — 임시 사고 그래프 내 유사 개념 쌍 탐지 및 공통부 추출."""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations

from ..entities.node import Node
from ..entities.edge import Edge
from .temp_thought_graph import TempThoughtGraph
from ... import config


# ── 유사도 계산 ───────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _overlap_ratio(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard 유사도 (이웃 집합 중첩 비율)."""
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _adaptive_alpha(neighbor_count: int) -> float:
    """이웃 수에 따른 α 결정.

    이웃이 적으면 임베딩만, 많으면 overlap 비중 증가.
    """
    if neighbor_count < config.DIFFERENTIATION_MIN_NEIGHBORS:
        return 1.0
    alpha = 1.0 - (neighbor_count / config.DIFFERENTIATION_ALPHA_DECAY_RATE)
    return max(config.DIFFERENTIATION_MIN_ALPHA, alpha)


def composite_score(
    node_a: Node,
    node_b: Node,
    neighbors_a: set[str],
    neighbors_b: set[str],
) -> float:
    """두 노드 간 복합 유사도 점수를 계산한다.

    score = α × cosine_sim(emb_A, emb_B) + (1-α) × overlap_ratio
    """
    if node_a.embedding is None or node_b.embedding is None:
        return 0.0

    cos_sim = _cosine(node_a.embedding, node_b.embedding)

    neighbor_count = max(len(neighbors_a), len(neighbors_b))
    alpha = _adaptive_alpha(neighbor_count)

    ovlp = _overlap_ratio(neighbors_a, neighbors_b)

    return alpha * cos_sim + (1.0 - alpha) * ovlp


# ── 결과 타입 ─────────────────────────────────────────────────────────────────

@dataclass
class DifferentiationResult:
    abstract_node: Node            # 새로 생성된 공통 추상 노드
    child_a: Node                  # 분화된 원본 노드 A
    child_b: Node                  # 분화된 원본 노드 B
    edges_added: list[Edge]        # 추가된 엣지 목록


# ── 공통부 추출 ───────────────────────────────────────────────────────────────

def _centroid(emb_a: list[float], emb_b: list[float]) -> list[float]:
    return [(a + b) / 2.0 for a, b in zip(emb_a, emb_b)]


def _make_abstract_node(
    node_a: Node,
    node_b: Node,
) -> Node:
    """두 노드의 centroid 임베딩으로 추상 공통 노드를 생성한다."""
    assert node_a.embedding is not None
    assert node_b.embedding is not None
    centroid = _centroid(node_a.embedding, node_b.embedding)
    now = datetime.now(timezone.utc)
    # address_hash: UUID 기반 (scope prefix "abstract::" 로 분리)
    import hashlib
    raw = f"abstract::{uuid.uuid4()}"
    address_hash = hashlib.sha256(raw.encode()).hexdigest()[:32]

    return Node(
        address_hash=address_hash,
        node_kind="concept",
        formation_source="differentiation",
        labels=[],          # 레이블 없는 순수 구조 노드
        is_abstract=True,
        trust_score=config.COMMIT_TRUST_WEAK,
        stability_score=config.COMMIT_STABILITY_WEAK,
        is_active=True,
        embedding=centroid,
        payload={},
        created_at=now,
        updated_at=now,
    )


def _make_differentiation_edge(
    source_hash: str,
    target_hash: str,
    now: datetime,
) -> Edge:
    return Edge(
        edge_id=str(uuid.uuid4()),
        source_hash=source_hash,
        target_hash=target_hash,
        edge_family="concept",
        connect_type="neutral",
        provenance_source="differentiation",
        proposed_connect_type="differentiation",
        proposal_reason="공통부 추출로 연결된 하위 개념",
        translation_confidence=None,
        is_temporary=True,       # 커밋 전까지 임시
        created_at=now,
        updated_at=now,
    )


# ── 메인 실행 ─────────────────────────────────────────────────────────────────

def run(tg: TempThoughtGraph) -> list[DifferentiationResult]:
    """임시 사고 그래프 내 모든 노드 쌍을 검사해 유사 쌍을 분화한다.

    - 임베딩 없는 노드는 건너뜀
    - 목표 노드는 분화 대상에서 제외
    - 결과로 생성된 추상 노드와 엣지를 TempThoughtGraph에 즉시 반영

    Returns:
        발생한 분화 결과 목록 (없으면 빈 리스트)
    """
    results: list[DifferentiationResult] = []

    # 추상 노드는 분화 후보에서 제외한다.
    # - 추상 노드는 이미 분화 결과물이므로 재분화 대상이 아니다.
    # - 포함하면 루프마다 노드 수가 자기 증폭식으로 늘어난다.
    nodes = [
        n for n in tg.all_nodes()
        if n.embedding is not None
        and n.is_active
        and not n.is_abstract
        and n.address_hash != tg.goal_hash
    ]

    # 이웃 집합을 순회 전 한 번만 계산해서 캐싱한다.
    neighbor_cache: dict[str, set[str]] = {
        n.address_hash: tg.neighbor_hashes(n.address_hash)
        for n in nodes
    }

    for node_a, node_b in combinations(nodes, 2):
        # 이미 분화한 쌍은 건너뛴다.
        if tg.is_differentiated(node_a.address_hash, node_b.address_hash):
            continue

        neighbors_a = neighbor_cache[node_a.address_hash]
        neighbors_b = neighbor_cache[node_b.address_hash]

        score = composite_score(node_a, node_b, neighbors_a, neighbors_b)

        if score < config.DIFFERENTIATION_THRESHOLD:
            continue

        # 공통 추상 노드 생성
        abstract_node = _make_abstract_node(node_a, node_b)
        now = datetime.now(timezone.utc)

        edge_to_a = _make_differentiation_edge(
            abstract_node.address_hash, node_a.address_hash, now
        )
        edge_to_b = _make_differentiation_edge(
            abstract_node.address_hash, node_b.address_hash, now
        )

        tg.add_node(abstract_node)
        tg.add_edge(edge_to_a)
        tg.add_edge(edge_to_b)
        tg.mark_differentiated(node_a.address_hash, node_b.address_hash)

        results.append(
            DifferentiationResult(
                abstract_node=abstract_node,
                child_a=node_a,
                child_b=node_b,
                edges_added=[edge_to_a, edge_to_b],
            )
        )

    return results
