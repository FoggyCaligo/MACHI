from __future__ import annotations

import json
from typing import Any

from ..goal import GOAL_ROOT_HASH, GLOBAL_GOAL_AXIS_SEEDS
from ..profile import is_profile_reference_edge, is_user_profile_node
from ..thinking import relation_quality
from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER

AnswerContract = dict[str, Any]


def build_answer_contract(conclusion) -> AnswerContract:
    """Build a mode-free GraphToLang SurfaceFrame from the final conclusion graph."""

    node_map = {node.address_hash: node for node in conclusion.nodes}
    edge_by_id = {edge.edge_id: edge for edge in conclusion.edges}
    identity_names = {ANCHOR_USER: "사용자", ANCHOR_ASSISTANT: "AI"}
    internal_hashes = {GOAL_ROOT_HASH, *(seed.node_hash for seed in GLOBAL_GOAL_AXIS_SEEDS)}
    if conclusion.goal_hash:
        internal_hashes.add(conclusion.goal_hash)

    def is_internal_profile_hash(address_hash: str) -> bool:
        node = node_map.get(address_hash)
        return bool(node and is_user_profile_node(node))

    def is_verbalizable_hash(address_hash: str) -> bool:
        return address_hash not in internal_hashes and not is_internal_profile_hash(address_hash)

    def node_label(address_hash: str) -> str:
        if address_hash in identity_names:
            return identity_names[address_hash]
        node = node_map.get(address_hash)
        if node and node.labels:
            return node.labels[0]
        return address_hash[:8]

    def display_degree(address_hash: str) -> int:
        degree = 0
        for edge in conclusion.edges:
            if edge.is_temporary and edge.payload.get("view_scope") != "input_sentence":
                continue
            if is_profile_reference_edge(edge):
                continue
            if not is_verbalizable_hash(edge.source_hash) or not is_verbalizable_hash(edge.target_hash):
                continue
            if address_hash in {edge.source_hash, edge.target_hash}:
                degree += 1
        return degree

    answer_graphs = [graph for graph in conclusion.selected_graphs if not graph.has_conflict_structure]
    conflict_graphs = [graph for graph in conclusion.selected_graphs if graph.has_conflict_structure]
    selected_graphs = answer_graphs or conflict_graphs

    if selected_graphs:
        primary_hashes = _rank_hashes(
            _primary_candidates(selected_graphs),
            node_map,
            node_label,
            is_verbalizable_hash,
            display_degree,
            limit=5,
        )
        supporting_hashes = _rank_hashes(
            _supporting_candidates(selected_graphs) - set(primary_hashes),
            node_map,
            node_label,
            is_verbalizable_hash,
            display_degree,
            limit=7,
        )
        frames = _build_conclusion_frames(
            selected_graphs,
            primary_hashes,
            edge_by_id,
            node_label,
            is_verbalizable_hash,
            limit_per_node=4,
        )
    else:
        primary_hashes = _rank_hashes(
            set(conclusion.key_hashes),
            node_map,
            node_label,
            is_verbalizable_hash,
            display_degree,
            limit=5,
        )
        supporting_hashes = _rank_hashes(
            set(conclusion.ref_hashes) - set(primary_hashes),
            node_map,
            node_label,
            is_verbalizable_hash,
            display_degree,
            limit=7,
        )
        frames = _build_input_frames(
            primary_hashes,
            conclusion.edges,
            node_label,
            is_verbalizable_hash,
            limit_per_node=4,
        )

    conflicts = _build_conflict_frames(conflict_graphs, node_label, is_verbalizable_hash, limit=2)
    return {
        "contract_type": "surface_frame",
        "source": "conclusion_graph",
        "meaning": "입력그래프, 세계그래프, 목적그래프의 상호작용으로 최종 생성된 결론 그래프의 GraphToLang 언어화용 투영",
        "continuity": conclusion.topic_continuity,
        "max_sentences": 5 if conflicts else 4,
        "focus": {
            "primary": [node_label(h) for h in primary_hashes],
            "supporting": [node_label(h) for h in supporting_hashes],
        },
        "frames": frames,
        "conflicts": conflicts,
    }


def render_answer_contract(contract: AnswerContract) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2)


def _primary_candidates(graphs) -> set[str]:
    candidates: set[str] = set()
    for graph in graphs:
        candidates.update(graph.core_hashes)
        candidates.update(graph.action_hashes)
        if not candidates:
            candidates.update(graph.input_hashes)
        if not candidates:
            candidates.update(graph.node_hashes)
    return candidates


def _supporting_candidates(graphs) -> set[str]:
    candidates: set[str] = set()
    for graph in graphs:
        candidates.update(graph.bridge_hashes)
        candidates.update(graph.condition_hashes)
        candidates.update(graph.exception_hashes)
        candidates.update(graph.node_hashes)
    return candidates


def _rank_hashes(hashes, node_map, node_label, is_verbalizable_hash, display_degree, *, limit: int) -> list[str]:
    ranked: list[str] = []
    seen_labels: set[str] = set()
    for h in sorted(
        (value for value in hashes if is_verbalizable_hash(value)),
        key=lambda value: (-display_degree(value), node_label(value), value),
    ):
        node = node_map.get(h)
        if node and (node.is_abstract or not node.labels):
            continue
        label = node_label(h)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        ranked.append(h)
        if len(ranked) >= limit:
            break
    return ranked


def _build_conclusion_frames(graphs, primary_hashes, edge_by_id, node_label, is_verbalizable_hash, *, limit_per_node: int):
    frames: list[dict[str, Any]] = []
    for graph in graphs:
        for source_hash in primary_hashes:
            if source_hash not in graph.node_hashes:
                continue
            relations = _surface_relations_from_graph(
                source_hash,
                graph,
                edge_by_id,
                node_label,
                is_verbalizable_hash,
                limit=limit_per_node,
            )
            role = _node_role_in_graph(source_hash, graph)
            if relations or role in {"core", "action", "bridge"}:
                frames.append({"source": node_label(source_hash), "graph_role": role, "relations": relations})
    return _dedupe_frames(frames)


def _build_input_frames(primary_hashes, edges, node_label, is_verbalizable_hash, *, limit_per_node: int):
    frames: list[dict[str, Any]] = []
    for source_hash in primary_hashes:
        relations = _surface_relations_from_edges(
            source_hash,
            edges,
            node_label,
            is_verbalizable_hash,
            limit=limit_per_node,
        )
        frames.append({"source": node_label(source_hash), "graph_role": "input", "relations": relations})
    return _dedupe_frames(frames)


def _surface_relations_from_graph(source_hash, graph, edge_by_id, node_label, is_verbalizable_hash, *, limit: int):
    ranked = []
    for edge_id in graph.edge_ids:
        edge = edge_by_id.get(edge_id)
        if edge is None or edge.is_temporary or is_profile_reference_edge(edge):
            continue
        if source_hash not in {edge.source_hash, edge.target_hash}:
            continue
        if not is_verbalizable_hash(edge.source_hash) or not is_verbalizable_hash(edge.target_hash):
            continue
        score = relation_quality.score_edge_relation(edge, graph).score
        if score > 0.0:
            ranked.append((score, edge))
    ranked.sort(key=lambda item: (-item[0], -item[1].edge_weight, item[1].edge_id))
    return [_to_surface_relation(source_hash, edge, node_label) for _, edge in ranked[:limit]]


def _surface_relations_from_edges(source_hash, edges, node_label, is_verbalizable_hash, *, limit: int):
    ranked = []
    for edge in edges:
        if edge.is_temporary and edge.payload.get("view_scope") != "input_sentence":
            continue
        if is_profile_reference_edge(edge):
            continue
        if source_hash not in {edge.source_hash, edge.target_hash}:
            continue
        if not is_verbalizable_hash(edge.source_hash) or not is_verbalizable_hash(edge.target_hash):
            continue
        score = max(0.0, edge.edge_weight) * max(0.0, edge.trust_score)
        if score > 0.0:
            ranked.append((score, edge))
    ranked.sort(key=lambda item: (-item[0], -item[1].edge_weight, item[1].edge_id))
    return [_to_surface_relation(source_hash, edge, node_label) for _, edge in ranked[:limit]]


def _to_surface_relation(source_hash, edge, node_label):
    if edge.source_hash == source_hash:
        target_hash = edge.target_hash
        direction = "out"
    else:
        target_hash = edge.source_hash
        direction = "in"
    return {"target": node_label(target_hash), "relation": _relation_label(edge.connect_type, direction=direction)}


def _relation_label(connect_type: str, *, direction: str) -> str:
    if connect_type == "flow":
        return "이어짐" if direction == "out" else "이어져 옴"
    if connect_type == "opposite":
        return "대조됨"
    if connect_type == "conflict":
        return "충돌함"
    return "관련됨"


def _node_role_in_graph(address_hash: str, graph) -> str:
    if address_hash in graph.core_hashes:
        return "core"
    if address_hash in graph.action_hashes:
        return "action"
    if address_hash in graph.bridge_hashes:
        return "bridge"
    if address_hash in graph.condition_hashes:
        return "condition"
    if address_hash in graph.exception_hashes:
        return "exception"
    if address_hash in graph.input_hashes:
        return "input"
    return "supporting"


def _build_conflict_frames(graphs, node_label, is_verbalizable_hash, *, limit: int):
    frames = []
    for graph in graphs[:limit]:
        lines = []
        for path in graph.conflict_paths:
            for step in path.steps:
                if not is_verbalizable_hash(step.source_hash) or not is_verbalizable_hash(step.target_hash):
                    continue
                lines.append(f"{node_label(step.source_hash)} -> {node_label(step.target_hash)}")
                if len(lines) >= 3:
                    break
            if len(lines) >= 3:
                break
        frames.append(
            {
                "current": _labels_from_hashes(graph.core_hashes, node_label, is_verbalizable_hash, limit=4),
                "previous": _labels_from_hashes(
                    graph.exception_hashes | graph.condition_hashes,
                    node_label,
                    is_verbalizable_hash,
                    limit=4,
                ),
                "conflicts": lines,
                "uncertainty": round(graph.uncertainty, 3),
            }
        )
    return frames


def _labels_from_hashes(hashes, node_label, is_verbalizable_hash, *, limit: int):
    labels: list[str] = []
    for h in sorted(hashes, key=lambda value: node_label(value)):
        if not is_verbalizable_hash(h):
            continue
        label = node_label(h)
        if label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    return labels


def _dedupe_frames(frames):
    deduped = []
    seen_sources = set()
    seen_relations = set()
    for frame in frames:
        source_key = (frame["source"], frame["graph_role"])
        unique_relations = []
        for relation in frame["relations"]:
            relation_key = (frame["source"], relation["target"], relation["relation"])
            if relation_key in seen_relations:
                continue
            seen_relations.add(relation_key)
            unique_relations.append(relation)
        if source_key in seen_sources and not unique_relations:
            continue
        seen_sources.add(source_key)
        deduped.append({**frame, "relations": unique_relations})
    return deduped
