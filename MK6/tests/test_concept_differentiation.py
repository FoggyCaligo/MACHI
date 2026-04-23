"""ConceptDifferentiation 단위 테스트 — Ollama 없이 실행."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from MK6.core.entities.node import Node
from MK6.core.thinking.temp_thought_graph import TempThoughtGraph
from MK6.core.thinking.concept_differentiation import (
    composite_score, run as run_differentiation,
)
import MK6.config as cfg


def _node(labels: list[str], embedding: list[float], n_neighbors: int = 0) -> Node:
    now = datetime.now(timezone.utc)
    return Node(
        address_hash=uuid.uuid4().hex[:32],
        node_kind="concept",
        formation_source="ingest",
        labels=labels,
        is_abstract=False,
        trust_score=0.5,
        stability_score=0.5,
        is_active=True,
        embedding=embedding,
        payload={},
        created_at=now,
        updated_at=now,
    )


def _unit(v: list[float]) -> list[float]:
    """벡터를 단위 벡터로 정규화."""
    import math
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def test_composite_score_identical_vectors():
    """동일 임베딩은 최고 점수."""
    emb = _unit([1.0, 0.0, 0.0])
    a = _node(["A"], emb)
    b = _node(["B"], emb)
    score = composite_score(a, b, set(), set())
    assert score == pytest.approx(1.0, abs=1e-5)


def test_composite_score_orthogonal_vectors():
    """직교 벡터는 낮은 점수 (이웃 없으면 α=1.0, cosine=0)."""
    a = _node(["A"], _unit([1.0, 0.0]))
    b = _node(["B"], _unit([0.0, 1.0]))
    score = composite_score(a, b, set(), set())
    assert score == pytest.approx(0.0, abs=1e-5)


def test_composite_score_overlap_contribution():
    """이웃이 많으면 overlap이 점수에 기여한다."""
    emb_a = _unit([1.0, 0.0])
    emb_b = _unit([0.0, 1.0])
    # 공유 이웃 3, 비공유 0 → overlap_ratio=1.0
    # DIFFERENTIATION_MIN_NEIGHBORS가 3이므로 3개 이상이어야 alpha < 1.0이 됨
    shared = {"x", "y", "z"}
    score = composite_score(_node(["A"], emb_a), _node(["B"], emb_b), shared, shared)
    # α < 1.0 when neighbors >= MIN_NEIGHBORS → overlap 기여
    assert score > 0.0


def test_run_detects_similar_pair():
    """유사한 두 노드 쌍을 탐지하고 추상 노드를 생성한다."""
    emb = _unit([1.0, 0.0, 0.0])
    a = _node(["사과"], emb)
    b = _node(["apple"], emb)  # 동일 임베딩 → score=1.0 > threshold

    tg = TempThoughtGraph()
    tg.add_node(a)
    tg.add_node(b)

    results = run_differentiation(tg)
    assert len(results) == 1

    r = results[0]
    assert r.abstract_node.is_abstract is True
    assert r.abstract_node.labels == []
    assert len(r.edges_added) == 2


def test_run_skips_dissimilar_pair():
    """직교 벡터 → 점수 < threshold → 분화 없음."""
    a = _node(["A"], _unit([1.0, 0.0]))
    b = _node(["B"], _unit([0.0, 1.0]))

    tg = TempThoughtGraph()
    tg.add_node(a)
    tg.add_node(b)

    results = run_differentiation(tg)
    assert len(results) == 0


def test_run_skips_goal_node():
    """목표 노드는 분화 대상에서 제외된다."""
    emb = _unit([1.0, 0.0])
    goal = _node(["목표"], emb)
    other = _node(["A"], emb)

    tg = TempThoughtGraph()
    tg.set_goal_node(goal)
    tg.add_node(other)

    results = run_differentiation(tg)
    # goal과 other는 동일 임베딩이지만 goal이 제외되므로 쌍이 없음
    assert len(results) == 0


def test_run_abstract_node_added_to_graph():
    """생성된 추상 노드가 TempThoughtGraph에 반영된다."""
    emb = _unit([1.0, 0.0])
    a = _node(["X"], emb)
    b = _node(["Y"], emb)

    tg = TempThoughtGraph()
    tg.add_node(a)
    tg.add_node(b)

    before_count = len(tg.all_nodes())
    run_differentiation(tg)
    after_count = len(tg.all_nodes())

    assert after_count == before_count + 1
