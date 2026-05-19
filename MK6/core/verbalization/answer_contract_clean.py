from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from ..goal import GOAL_ROOT_HASH, GLOBAL_GOAL_AXIS_SEEDS
from ..profile import is_profile_reference_edge, is_user_profile_node
from ..thinking import relation_quality
from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER

if TYPE_CHECKING:
    from ..entities.edge import Edge
    from ..entities.node import Node
    from ..thinking.conclusion_graph import ConclusionGraph
    from ..thinking.thought_engine import ConclusionView


INPUT_DELTA_PRIMARY_LIMIT = 2
INPUT_DELTA_SUPPORT_LIMIT = 0


@dataclass(frozen=True, slots=True)
class SurfaceResponse:
    mode: str
    continuity: str
    max_sentences: int
    copy_user_input: bool = False
    list_raw_edges: bool = False
    expose_internal_fields: bool = False


@dataclass(frozen=True, slots=True)
class SurfaceFocus:
    primary: list[str] = field(default_factory=list)
    supporting: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SurfaceEdge:
    target: str
    edge_family: str
    connect_type: str
    direction: str
    weight: float
    trust: float
    support: int
    score: float


@dataclass(frozen=True, slots=True)
class SurfaceNodeFrame:
    source: str
    role: str
    edges: list[SurfaceEdge] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SurfaceConflictFrame:
    current: list[str] = field(default_factory=list)
    previous: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    uncertainty: float = 0.0


@dataclass(frozen=True, slots=True)
class AnswerContract:
    """GraphToLang에 넘길 결론그래프의 표면화 전용 프레임.

    LLM은 WorldGraph/TempThoughtGraph/raw ConclusionGraph를 직접 보지 않는다.
    이 계약은 selected ConclusionGraph 또는 입력 변화량을 JSON형 SurfaceFrame으로
    투영한 결과이며, 자연어 요약문이나 키워드 나열을 별도 본체로 두지 않는다.
    """

    contract_type: str
    source: str
    response: SurfaceResponse
    focus: SurfaceFocus
    frames: list[SurfaceNodeFrame] = field(default_factory=list)
    conflicts: list[SurfaceConflictFrame] = field(default_factory=list)


def build_answer_contract(conclusion: "ConclusionView") -> AnswerContract:
    node_map = {node.address_hash: node for node in conclusion.nodes}
    edge_by_id = {edge.edge_id: edge for edge in conclusion.edges}
    identity_names = {ANCHOR_USER: "사용자", ANCHOR_ASSISTANT: "AI"}
    internal_goal_hashes = {GOAL_ROOT_HASH, *(seed.node_hash for seed in GLOBAL_GOAL_AXIS_SEEDS)}
    if conclusion.goal_hash:
        internal_goal_hashes.add(conclusion.goal_hash)

    def is_internal_profile_hash(address_hash: str) -> bool:
        node = node_map.get(address_hash)
        return bool(node and is_user_profile_node(node))

    def is_verbalizable_hash(address_hash: str) -> bool:
        return address_hash not in internal_goal_hashes and not is_internal_profile_hash(address_hash)

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
        primary_hashes = _rank_selected_hashes(
            selected_graphs,
            node_map,
            node_label,
            is_verbalizable_hash,
            display_degree,
            limit=5,
        )
        supporting_hashes = _rank_supporting_hashes(
            selected_graphs,
            primary_hashes,
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
        source = "conclusion_graph"
    else:
        primary_hashes = _rank_fallback_hashes(
            set(conclusion.key_hashes),
            conclusion.keyword_scores,
            node_map,
            node_label,
            is_verbalizable_hash,
            display_degree,
            limit=INPUT_DELTA_PRIMARY_LIMIT,
        )
        supporting_hashes = _rank_fallback_hashes(
            set(conclusion.ref_hashes) - set(primary_hashes),
            conclusion.keyword_scores,
            node_map,
            node_label,
            is_verbalizable_hash,
            display_degree,
            limit=INPUT_DELTA_SUPPORT_LIMIT,
        )
        frames: list[SurfaceNodeFrame] = []
        source = "input_delta"

    conflicts = _build_conflict_frames(
        conflict_graphs,
        node_label,
        is_verbalizable_hash,
        limit=2,
    )
    mode = _select_mode(
        has_conflict=bool(conflicts),
        has_conclusion=bool(answer_graphs),
        has_focus=bool(primary_hashes or supporting_hashes),
    )

    return AnswerContract(
        contract_type="surface_frame",
        source=source,
        response=SurfaceResponse(
            mode=mode,
            continuity=conclusion.topic_continuity,
            max_sentences=5 if mode == "conflict_resolution" else 1 if mode == "brief_acknowledgement" else 4,
        ),
        focus=SurfaceFocus(
            primary=[node_label(h) for h in primary_hashes],
            supporting=[node_label(h) for h in supporting_hashes],
        ),
        frames=frames,
        conflicts=conflicts,
    )


def render_answer_contract(contract: AnswerContract) -> str:
    """SurfaceFrame을 JSON형 텍스트로 직렬화한다."""

    return json.dumps(asdict(contract), ensure_ascii=False, indent=2)


def _select_mode(*, has_conflict: bool, has_conclusion: bool, has_focus: bool) -> str:
    if has_conflict:
        return "conflict_resolution"
    if has_conclusion:
        return "answer_from_conclusion"
    if has_focus:
        return "brief_acknowledgement"
    return "minimal_response"


def _rank_selected_hashes(
    graphs: list["ConclusionGraph"],
    node_map: dict[str, "Node"],
    node_label,
    is_verbalizable_hash,
    display_degree,
    *,
    limit: int,
) -> list[str]:
    candidates: set[str] = set()
    for graph in graphs:
        candidates.update(graph.core_hashes)
        candidates.update(graph.action_hashes)
        if not candidates:
            candidates.update(graph.input_hashes)
        if not candidates:
            candidates.update(graph.node_hashes)
    return _rank_hashes(candidates, node_map, node_label, is_verbalizable_hash, display_degree, limit=limit)


def _rank_supporting_hashes(
    graphs: list["ConclusionGraph"],
    primary_hashes: list[str],
    node_map: dict[str, "Node"],
    node_label,
    is_verbalizable_hash,
    display_degree,
    *,
    limit: int,
) -> list[str]:
    primary = set(primary_hashes)
    candidates: set[str] = set()
    for graph in graphs:
        candidates.update(graph.bridge_hashes)
        candidates.update(graph.condition_hashes)
        candidates.update(graph.exception_hashes)
        candidates.update(graph.node_hashes - primary)
    return _rank_hashes(candidates - primary, node_map, node_label, is_verbalizable_hash, display_degree, limit=limit)


def _rank_fallback_hashes(
    hashes: set[str],
    keyword_scores: dict[str, float],
    node_map: dict[str, "Node"],
    node_label,
    is_verbalizable_hash,
    display_degree,
    *,
    limit: int,
) -> list[str]:
    if limit <= 0:
        return []
    ranked = _rank_hashes(hashes, node_map, node_label, is_verbalizable_hash, display_degree, limit=limit * 3)
    return sorted(
        ranked,
        key=lambda h: (-keyword_scores.get(h, 0.0), -display_degree(h), node_label(h), h),
    )[:limit]


def _rank_hashes(
    hashes: set[str],
    node_map: dict[str, "Node"],
    node_label,
    is_verbalizable_hash,
    display_degree,
    *,
    limit: int,
) -> list[str]:
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


def _build_conclusion_frames(
    graphs: list["ConclusionGraph"],
    primary_hashes: list[str],
    edge_by_id: dict[str, "Edge"],
    node_label,
    is_verbalizable_hash,
    *,
    limit_per_node: int,
) -> list[SurfaceNodeFrame]:
    frames: list[SurfaceNodeFrame] = []
    for graph in graphs:
        source_hashes = primary_hashes or _rank_hashes(
            set(graph.node_hashes),
            {},
            node_label,
            is_verbalizable_hash,
            lambda _h: 0,
            limit=4,
        )
        for source_hash in source_hashes:
            if source_hash not in graph.node_hashes:
                continue
            edges = _surface_edges_from_graph(source_hash, graph, edge_by_id, node_label, is_verbalizable_hash, limit=limit_per_node)
            role = _node_role_in_graph(source_hash, graph)
            if edges or role in {"core", "action", "bridge"}:
                frames.append(SurfaceNodeFrame(source=node_label(source_hash), role=role, edges=edges))
    return _dedupe_frames(frames)


def _surface_edges_from_graph(
    source_hash: str,
    graph: "ConclusionGraph",
    edge_by_id: dict[str, "Edge"],
    node_label,
    is_verbalizable_hash,
    *,
    limit: int,
) -> list[SurfaceEdge]:
    ranked: list[tuple[float, "Edge"]] = []
    for edge_id in graph.edge_ids:
        edge = edge_by_id.get(edge_id)
        if edge is None or edge.is_temporary or is_profile_reference_edge(edge):
            continue
        if source_hash not in {edge.source_hash, edge.target_hash}:
            continue
        if not is_verbalizable_hash(edge.source_hash) or not is_verbalizable_hash(edge.target_hash):
            continue
        score = relation_quality.score_edge_relation(edge, graph).score
        if score <= 0.0:
            continue
        ranked.append((score, edge))
    ranked.sort(key=lambda item: (-item[0], -item[1].edge_weight, item[1].edge_id))
    return [_to_surface_edge(source_hash, edge, node_label, score) for score, edge in ranked[:limit]]


def _to_surface_edge(source_hash: str, edge: "Edge", node_label, score: float) -> SurfaceEdge:
    if edge.source_hash == source_hash:
        target_hash = edge.target_hash
        direction = "out"
    else:
        target_hash = edge.source_hash
        direction = "in"
    return SurfaceEdge(
        target=node_label(target_hash),
        edge_family=edge.edge_family,
        connect_type=edge.connect_type,
        direction=direction,
        weight=round(edge.edge_weight, 3),
        trust=round(edge.trust_score, 3),
        support=edge.support_count,
        score=round(score, 3),
    )


def _node_role_in_graph(address_hash: str, graph: "ConclusionGraph") -> str:
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


def _build_conflict_frames(
    graphs: list["ConclusionGraph"],
    node_label,
    is_verbalizable_hash,
    *,
    limit: int,
) -> list[SurfaceConflictFrame]:
    frames: list[SurfaceConflictFrame] = []
    for graph in graphs[:limit]:
        current = _labels_from_hashes(graph.core_hashes, node_label, is_verbalizable_hash, limit=4)
        previous = _labels_from_hashes(
            graph.exception_hashes | graph.condition_hashes,
            node_label,
            is_verbalizable_hash,
            limit=4,
        )
        conflicts: list[str] = []
        for path in graph.conflict_paths[:3]:
            for step in path.steps:
                if not is_verbalizable_hash(step.source_hash) or not is_verbalizable_hash(step.target_hash):
                    continue
                conflicts.append(f"{node_label(step.source_hash)} -> {node_label(step.target_hash)}")
                if len(conflicts) >= 3:
                    break
            if len(conflicts) >= 3:
                break
        frames.append(
            SurfaceConflictFrame(
                current=current,
                previous=previous,
                conflicts=conflicts,
                uncertainty=round(graph.uncertainty, 3),
            )
        )
    return frames


def _labels_from_hashes(hashes, node_label, is_verbalizable_hash, *, limit: int) -> list[str]:
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


def _dedupe_frames(frames: list[SurfaceNodeFrame]) -> list[SurfaceNodeFrame]:
    deduped: list[SurfaceNodeFrame] = []
    seen_sources: set[tuple[str, str]] = set()
    seen_edges: set[tuple[str, str, str, str]] = set()
    for frame in frames:
        source_key = (frame.source, frame.role)
        unique_edges: list[SurfaceEdge] = []
        for edge in frame.edges:
            edge_key = (frame.source, edge.target, edge.connect_type, edge.direction)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            unique_edges.append(edge)
        if source_key in seen_sources and not unique_edges:
            continue
        seen_sources.add(source_key)
        deduped.append(SurfaceNodeFrame(source=frame.source, role=frame.role, edges=unique_edges))
    return deduped
