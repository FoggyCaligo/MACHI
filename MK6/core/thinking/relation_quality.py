"""RelationQuality — ConclusionGraph relation 품질을 구조적으로 평가한다.

이 모듈은 edge에 새 의미 라벨을 붙이지 않는다. kind/ontology 문자열로 관계를
해석하지 않고, 이미 존재하는 edge_family + connect_type + 방향/상태값과
ConclusionGraph 내부 위치만으로 품질을 계산한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..entities.edge import Edge
from .conclusion_graph import ConclusionGraph
from .temp_thought_graph import TempThoughtGraph


@dataclass(frozen=True, slots=True)
class EdgeRelationQuality:
    edge_id: str
    score: float
    support_strength: float
    goal_relevance: float
    bridge_value: float
    restatement_risk: float
    conflict_pressure: float


@dataclass(frozen=True, slots=True)
class GraphRelationQuality:
    score: float
    average_edge_score: float
    support_strength: float
    goal_relevance: float
    bridge_value: float
    restatement_risk: float
    conflict_pressure: float
    edge_scores: dict[str, EdgeRelationQuality]


def score_graph_relations(tg: TempThoughtGraph, graph: ConclusionGraph) -> GraphRelationQuality:
    """ConclusionGraph 안의 relation 품질을 계산한다."""
    edge_scores: dict[str, EdgeRelationQuality] = {}
    support_edge_ids = _path_edge_ids(graph.support_paths)
    goal_edge_ids = _path_edge_ids(graph.goal_paths)

    for edge_id in graph.edge_ids:
        edge = tg.get_edge(edge_id)
        if edge is None:
            continue
        edge_scores[edge_id] = score_edge_relation(
            edge,
            graph,
            support_edge_ids=support_edge_ids,
            goal_edge_ids=goal_edge_ids,
        )

    if not edge_scores:
        return GraphRelationQuality(
            score=0.0,
            average_edge_score=0.0,
            support_strength=0.0,
            goal_relevance=0.0,
            bridge_value=0.0,
            restatement_risk=1.0,
            conflict_pressure=0.0,
            edge_scores={},
        )

    values = list(edge_scores.values())
    average_edge_score = sum(v.score for v in values) / len(values)
    support_strength = sum(v.support_strength for v in values) / len(values)
    goal_relevance = sum(v.goal_relevance for v in values) / len(values)
    bridge_value = sum(v.bridge_value for v in values) / len(values)
    restatement_risk = sum(v.restatement_risk for v in values) / len(values)
    conflict_pressure = sum(v.conflict_pressure for v in values) / len(values)

    score = average_edge_score
    score += support_strength * 0.20
    score += goal_relevance * 0.25
    score += bridge_value * 0.20
    score -= restatement_risk * 0.35
    score -= conflict_pressure * 0.20
    if graph.has_conflict_structure:
        score += min(0.20, conflict_pressure * 0.15)

    return GraphRelationQuality(
        score=max(0.0, score),
        average_edge_score=average_edge_score,
        support_strength=support_strength,
        goal_relevance=goal_relevance,
        bridge_value=bridge_value,
        restatement_risk=restatement_risk,
        conflict_pressure=conflict_pressure,
        edge_scores=edge_scores,
    )


def score_edge_relation(
    edge: Edge,
    graph: ConclusionGraph,
    *,
    support_edge_ids: set[str] | None = None,
    goal_edge_ids: set[str] | None = None,
) -> EdgeRelationQuality:
    """edge 하나의 relation 품질을 구조적으로 계산한다."""
    support_edge_ids = support_edge_ids or set()
    goal_edge_ids = goal_edge_ids or set()

    if edge.is_temporary:
        return EdgeRelationQuality(
            edge_id=edge.edge_id,
            score=0.0,
            support_strength=0.0,
            goal_relevance=0.0,
            bridge_value=0.0,
            restatement_risk=1.0,
            conflict_pressure=0.0,
        )

    base = max(0.0, edge.edge_weight) * max(0.0, edge.trust_score)
    connect_gain = _connect_gain(edge.connect_type)
    support_strength = base * connect_gain
    if edge.support_count > 0:
        support_strength += min(0.30, edge.support_count * 0.05)

    endpoints = {edge.source_hash, edge.target_hash}
    touches_input = bool(endpoints & graph.input_hashes)
    touches_goal = bool(endpoints & graph.goal_hashes)
    touches_bridge = bool(endpoints & graph.bridge_hashes)
    touches_core = bool(endpoints & graph.core_hashes)
    input_only = edge.source_hash in graph.input_hashes and edge.target_hash in graph.input_hashes

    goal_relevance = 0.0
    if edge.edge_id in goal_edge_ids:
        goal_relevance += 0.55
    if touches_goal:
        goal_relevance += 0.25
    if touches_core and graph.goal_paths:
        goal_relevance += 0.10

    bridge_value = 0.0
    if touches_bridge:
        bridge_value += 0.35
    if touches_input and not input_only:
        bridge_value += 0.20
    if touches_core and not input_only:
        bridge_value += 0.15

    restatement_risk = 0.0
    if input_only:
        restatement_risk += 0.70 if edge.connect_type == "neutral" else 0.45
    if edge.edge_id not in support_edge_ids and edge.edge_id not in goal_edge_ids and not touches_bridge:
        restatement_risk += 0.15

    conflict_pressure = max(0.0, edge.contradiction_pressure)
    conflict_pressure += max(0, edge.conflict_count) * 0.10
    if edge.connect_type == "conflict":
        conflict_pressure += 0.25

    score = support_strength
    score += goal_relevance * 0.35
    score += bridge_value * 0.30
    score -= restatement_risk * 0.45
    score -= conflict_pressure * 0.25

    return EdgeRelationQuality(
        edge_id=edge.edge_id,
        score=max(0.0, score),
        support_strength=support_strength,
        goal_relevance=goal_relevance,
        bridge_value=bridge_value,
        restatement_risk=restatement_risk,
        conflict_pressure=conflict_pressure,
    )


def rank_edges_for_contract(
    edges: list[Edge],
    graph_by_edge_id: dict[str, ConclusionGraph],
    tg: TempThoughtGraph,
) -> list[tuple[float, Edge]]:
    """AnswerContract EvidenceEdges용 edge ranking을 만든다."""
    ranked: list[tuple[float, Edge]] = []
    quality_cache: dict[str, GraphRelationQuality] = {}
    for edge in edges:
        graph = graph_by_edge_id.get(edge.edge_id)
        if graph is None:
            score = _fallback_edge_score(edge)
        else:
            if graph.graph_id not in quality_cache:
                quality_cache[graph.graph_id] = score_graph_relations(tg, graph)
            score = quality_cache[graph.graph_id].edge_scores.get(
                edge.edge_id,
                score_edge_relation(edge, graph),
            ).score
        ranked.append((score, edge))
    return sorted(ranked, key=lambda item: (-item[0], -item[1].edge_weight, item[1].edge_id))


def _fallback_edge_score(edge: Edge) -> float:
    if edge.is_temporary:
        return 0.0
    base = max(0.0, edge.edge_weight) * max(0.0, edge.trust_score)
    base *= _connect_gain(edge.connect_type)
    base += min(0.20, max(0, edge.support_count) * 0.04)
    base -= max(0.0, edge.contradiction_pressure) * 0.20
    return max(0.0, base)


def _path_edge_ids(paths) -> set[str]:
    return {edge_id for path in paths for edge_id in path.edge_ids}


def _connect_gain(connect_type: str) -> float:
    if connect_type == "flow":
        return 1.0
    if connect_type == "neutral":
        return 0.65
    if connect_type == "opposite":
        return 0.75
    if connect_type == "conflict":
        return 0.40
    return 0.50
