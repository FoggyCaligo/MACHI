from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from ..goal import GOAL_ROOT_HASH, GLOBAL_GOAL_AXIS_SEEDS
from ..profile import is_user_profile_node
from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER

if TYPE_CHECKING:
    from ..entities.node import Node
    from ..thinking.conclusion_graph import ConclusionGraph
    from ..thinking.thought_engine import ConclusionView


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
class SurfaceActionFrame:
    actor: str
    target: str
    target_display: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class SurfaceConflictFrame:
    current: list[str] = field(default_factory=list)
    previous: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    uncertainty: float = 0.0


@dataclass(frozen=True, slots=True)
class AnswerContract:
    """GraphToLang에 넘기는 결론 그래프 표면 계약."""

    contract_type: str
    source: str
    response: SurfaceResponse
    focus: SurfaceFocus
    frames: list[SurfaceNodeFrame] = field(default_factory=list)
    actions: list[SurfaceActionFrame] = field(default_factory=list)
    conflicts: list[SurfaceConflictFrame] = field(default_factory=list)


def build_answer_contract(conclusion: "ConclusionView") -> AnswerContract:
    node_map = {node.address_hash: node for node in conclusion.nodes}
    edge_by_id = {edge.edge_id: edge for edge in conclusion.edges}
    identity_names = {ANCHOR_USER: "사용자", ANCHOR_ASSISTANT: "AI"}
    internal_hashes = {GOAL_ROOT_HASH, *(seed.node_hash for seed in GLOBAL_GOAL_AXIS_SEEDS)}
    if conclusion.goal_hash:
        internal_hashes.add(conclusion.goal_hash)

    def is_internal_hash(address_hash: str) -> bool:
        node = node_map.get(address_hash)
        return address_hash in internal_hashes or bool(node and is_user_profile_node(node))

    def node_label(address_hash: str) -> str:
        if address_hash in identity_names:
            return identity_names[address_hash]
        node = node_map.get(address_hash)
        if node and node.labels:
            return node.labels[0]
        return address_hash[:8]

    selected_graphs = list(conclusion.selected_graphs)
    answer_graphs = [graph for graph in selected_graphs if not graph.has_conflict_structure]
    relation_graphs = answer_graphs or selected_graphs
    action_graphs = [graph for graph in relation_graphs if _is_turn_response_graph(graph, node_map)]
    non_action_graphs = [graph for graph in relation_graphs if graph not in action_graphs]

    actions = _build_action_frames(action_graphs, node_map, node_label)
    frames = _build_node_frames(non_action_graphs, edge_by_id, node_label, is_internal_hash)
    conflicts = _build_conflict_frames(
        [graph for graph in selected_graphs if graph.has_conflict_structure],
        node_label,
        is_internal_hash,
    )

    primary_hashes: list[str] = []
    supporting_hashes: list[str] = []
    if not actions:
        primary_hashes = _rank_graph_hashes(non_action_graphs, node_map, node_label, is_internal_hash, limit=5)
        supporting_hashes = _rank_supporting_hashes(non_action_graphs, primary_hashes, node_map, node_label, is_internal_hash, limit=7)

    mode = _select_mode(
        has_conflict=bool(conflicts),
        has_action=bool(actions),
        has_graph=bool(non_action_graphs),
    )

    return AnswerContract(
        contract_type="surface_frame",
        source="conclusion_graph",
        response=SurfaceResponse(
            mode=mode,
            continuity=conclusion.topic_continuity,
            max_sentences=5 if mode == "conflict_resolution" else 2 if mode == "perform_response_action" else 4,
        ),
        focus=SurfaceFocus(
            primary=[node_label(h) for h in primary_hashes],
            supporting=[node_label(h) for h in supporting_hashes],
        ),
        frames=frames,
        actions=actions,
        conflicts=conflicts,
    )


def render_answer_contract(contract: AnswerContract) -> str:
    return json.dumps(asdict(contract), ensure_ascii=False, indent=2)


def _select_mode(*, has_conflict: bool, has_action: bool, has_graph: bool) -> str:
    if has_conflict:
        return "conflict_resolution"
    if has_action:
        return "perform_response_action"
    if has_graph:
        return "answer_from_conclusion"
    return "minimal_response"


def _is_turn_response_graph(graph: "ConclusionGraph", node_map: dict[str, "Node"]) -> bool:
    for h in graph.action_hashes | graph.core_hashes:
        node = node_map.get(h)
        if node and node.payload.get("response_action"):
            return True
    return False


def _build_action_frames(graphs: list["ConclusionGraph"], node_map: dict[str, "Node"], node_label) -> list[SurfaceActionFrame]:
    result: list[SurfaceActionFrame] = []
    for graph in graphs:
        for action_hash in sorted(graph.action_hashes | graph.core_hashes):
            node = node_map.get(action_hash)
            if node is None or not node.payload.get("response_action"):
                continue
            actor_hash = node.payload.get("actor_hash") or ANCHOR_ASSISTANT
            target_hash = node.payload.get("target_hash") or ANCHOR_USER
            display_hashes = [h for h in node.payload.get("target_display_hashes", []) if isinstance(h, str)]
            result.append(SurfaceActionFrame(
                actor=node_label(actor_hash),
                target=node_label(target_hash),
                target_display=[node_label(h) for h in display_hashes],
                confidence=round(float(node.payload.get("confidence", graph.score)), 3),
            ))
    return result


def _rank_graph_hashes(graphs, node_map, node_label, is_internal_hash, *, limit: int) -> list[str]:
    candidates: set[str] = set()
    for graph in graphs:
        candidates.update(graph.action_hashes)
        candidates.update(graph.core_hashes)
        if not candidates:
            candidates.update(graph.node_hashes)
    return _dedupe_hashes(candidates, node_map, node_label, is_internal_hash, limit=limit)


def _rank_supporting_hashes(graphs, primary_hashes, node_map, node_label, is_internal_hash, *, limit: int) -> list[str]:
    primary = set(primary_hashes)
    candidates: set[str] = set()
    for graph in graphs:
        candidates.update(graph.bridge_hashes)
        candidates.update(graph.condition_hashes)
        candidates.update(graph.node_hashes - primary)
    return _dedupe_hashes(candidates - primary, node_map, node_label, is_internal_hash, limit=limit)


def _dedupe_hashes(hashes, node_map, node_label, is_internal_hash, *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for h in sorted(hashes, key=lambda value: (node_label(value), value)):
        if is_internal_hash(h):
            continue
        node = node_map.get(h)
        if node and (node.is_abstract or not node.labels):
            continue
        label = node_label(h)
        if label in seen:
            continue
        seen.add(label)
        result.append(h)
        if len(result) >= limit:
            break
    return result


def _build_node_frames(graphs: list["ConclusionGraph"], edge_by_id, node_label, is_internal_hash) -> list[SurfaceNodeFrame]:
    frames: list[SurfaceNodeFrame] = []
    seen: set[tuple[str, str]] = set()
    for graph in graphs:
        source_hashes = sorted((graph.action_hashes | graph.core_hashes) or graph.node_hashes)
        for source_hash in source_hashes:
            if is_internal_hash(source_hash):
                continue
            role = _node_role(source_hash, graph)
            key = (node_label(source_hash), role)
            if key in seen:
                continue
            seen.add(key)
            edges = _surface_edges(source_hash, graph, edge_by_id, node_label, is_internal_hash, limit=4)
            frames.append(SurfaceNodeFrame(source=node_label(source_hash), role=role, edges=edges))
    return frames


def _surface_edges(source_hash: str, graph: "ConclusionGraph", edge_by_id, node_label, is_internal_hash, *, limit: int) -> list[SurfaceEdge]:
    scored = []
    for edge_id in graph.edge_ids:
        edge = edge_by_id.get(edge_id)
        if edge is None or source_hash not in {edge.source_hash, edge.target_hash}:
            continue
        other_hash = edge.target_hash if edge.source_hash == source_hash else edge.source_hash
        if is_internal_hash(other_hash):
            continue
        if edge.is_temporary and edge.payload.get("view_scope") != "response_action":
            continue
        score = max(0.0, edge.edge_weight) * max(0.0, edge.trust_score)
        if score > 0.0:
            scored.append((score, edge))
    scored.sort(key=lambda item: (-item[0], item[1].edge_id))
    return [_to_surface_edge(source_hash, edge, node_label, score) for score, edge in scored[:limit]]


def _to_surface_edge(source_hash: str, edge, node_label, score: float) -> SurfaceEdge:
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


def _node_role(address_hash: str, graph: "ConclusionGraph") -> str:
    if address_hash in graph.action_hashes:
        return "action"
    if address_hash in graph.core_hashes:
        return "core"
    if address_hash in graph.bridge_hashes:
        return "bridge"
    if address_hash in graph.condition_hashes:
        return "condition"
    if address_hash in graph.exception_hashes:
        return "exception"
    if address_hash in graph.input_hashes:
        return "input"
    return "supporting"


def _build_conflict_frames(graphs: list["ConclusionGraph"], node_label, is_internal_hash) -> list[SurfaceConflictFrame]:
    result: list[SurfaceConflictFrame] = []
    for graph in graphs[:2]:
        current = [node_label(h) for h in sorted(graph.core_hashes) if not is_internal_hash(h)][:4]
        previous = [node_label(h) for h in sorted(graph.exception_hashes | graph.condition_hashes) if not is_internal_hash(h)][:4]
        result.append(SurfaceConflictFrame(
            current=current,
            previous=previous,
            relations=[],
            uncertainty=round(graph.uncertainty, 3),
        ))
    return result
