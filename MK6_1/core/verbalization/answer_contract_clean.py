from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from ..entities.translated_graph import ConceptPointer, EmptySlot, TranslatedGraph
from ..goal import GLOBAL_GOAL_AXIS_SEEDS, GOAL_ROOT_HASH
from ..profile import is_profile_reference_edge, is_user_profile_node
from ..thinking import relation_quality
from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER, compute_hash

if TYPE_CHECKING:
    from ..entities.edge import Edge
    from ..entities.node import Node
    from ..thinking.conclusion_graph import ConclusionGraph
    from ..thinking.thought_engine import ConclusionView


@dataclass(frozen=True, slots=True)
class SurfaceInput:
    text: str


@dataclass(frozen=True, slots=True)
class SurfaceResponse:
    continuity: str
    max_sentences: int
    may_use_user_input: bool = True
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
class SurfaceGraphSection:
    speaker: str = "system"
    usage: str = ""
    focus: SurfaceFocus = field(default_factory=SurfaceFocus)
    frames: list[SurfaceNodeFrame] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SurfaceConflictFrame:
    current: list[str] = field(default_factory=list)
    previous: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    uncertainty: float = 0.0


@dataclass(frozen=True, slots=True)
class AnswerContract:
    contract_type: str
    source: str
    input: SurfaceInput
    response: SurfaceResponse
    input_graph: SurfaceGraphSection = field(default_factory=SurfaceGraphSection)
    conclusion_graph: SurfaceGraphSection = field(default_factory=SurfaceGraphSection)
    search_graph: SurfaceGraphSection = field(default_factory=SurfaceGraphSection)
    conflicts: list[SurfaceConflictFrame] = field(default_factory=list)


def build_answer_contract(conclusion: "ConclusionView", translated: TranslatedGraph) -> AnswerContract:
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
            if edge.is_temporary or is_profile_reference_edge(edge):
                continue
            if not is_verbalizable_hash(edge.source_hash) or not is_verbalizable_hash(edge.target_hash):
                continue
            if address_hash in {edge.source_hash, edge.target_hash}:
                degree += 1
        return degree

    answer_graphs = [graph for graph in conclusion.selected_graphs if not graph.has_conflict_structure]
    conflict_graphs = [graph for graph in conclusion.selected_graphs if graph.has_conflict_structure]
    selected_graphs = answer_graphs or conflict_graphs

    input_graph = _build_input_graph_section(
        translated,
        conclusion,
        node_map,
        node_label,
        is_verbalizable_hash,
        display_degree,
    )
    conclusion_graph = _build_conclusion_graph_section(
        selected_graphs,
        conclusion,
        node_map,
        edge_by_id,
        node_label,
        is_verbalizable_hash,
        display_degree,
    )
    search_graph = _build_search_graph_section(
        conclusion,
        node_map,
        node_label,
        is_verbalizable_hash,
        display_degree,
    )
    conflicts = _build_conflict_frames(
        conflict_graphs,
        node_label,
        is_verbalizable_hash,
        limit=2,
    )

    return AnswerContract(
        contract_type="surface_frame",
        source="multi_graph_surface_frame",
        input=SurfaceInput(text=conclusion.user_input or ""),
        response=SurfaceResponse(
            continuity=conclusion.topic_continuity,
            max_sentences=5 if conflicts else 4,
        ),
        input_graph=input_graph,
        conclusion_graph=conclusion_graph,
        search_graph=search_graph,
        conflicts=conflicts,
    )


def render_answer_contract(contract: AnswerContract) -> str:
    return json.dumps(asdict(contract), ensure_ascii=False, indent=2)


def _build_input_graph_section(
    translated: TranslatedGraph,
    conclusion: "ConclusionView",
    node_map: dict[str, "Node"],
    node_label,
    is_verbalizable_hash,
    display_degree,
) -> SurfaceGraphSection:
    scored_hashes: dict[str, float] = {}
    for ref in translated.nodes:
        if isinstance(ref, ConceptPointer):
            scored_hashes[ref.address_hash] = max(scored_hashes.get(ref.address_hash, 0.0), ref.importance)
            continue
        hint = ref.concept_hint.strip()
        if not hint:
            continue
        address_hash = compute_hash(hint)
        if address_hash in node_map:
            scored_hashes[address_hash] = max(scored_hashes.get(address_hash, 0.0), ref.importance)

    input_hashes = {h for h in scored_hashes if is_verbalizable_hash(h)}
    primary_hashes = sorted(
        input_hashes,
        key=lambda h: (-scored_hashes.get(h, 0.0), -display_degree(h), node_label(h), h),
    )[:5]
    supporting_hashes = sorted(
        input_hashes - set(primary_hashes),
        key=lambda h: (-scored_hashes.get(h, 0.0), -display_degree(h), node_label(h), h),
    )[:7]

    frames = _build_input_frames(
        translated,
        node_map,
        node_label,
        is_verbalizable_hash,
        primary_hashes,
    )
    return SurfaceGraphSection(
        speaker="user",
        usage="User-attributed input graph. Treat its content as what the user said or implied, never as the assistant's self-description.",
        focus=SurfaceFocus(
            primary=[node_label(h) for h in primary_hashes],
            supporting=[node_label(h) for h in supporting_hashes],
        ),
        frames=frames,
    )


def _build_conclusion_graph_section(
    graphs: list["ConclusionGraph"],
    conclusion: "ConclusionView",
    node_map: dict[str, "Node"],
    edge_by_id: dict[str, "Edge"],
    node_label,
    is_verbalizable_hash,
    display_degree,
) -> SurfaceGraphSection:
    if not graphs:
        return SurfaceGraphSection()

    ranked_primary_hashes = _rank_selected_hashes(
        graphs,
        node_map,
        node_label,
        is_verbalizable_hash,
        display_degree,
        limit=5,
    )
    frames = _build_conclusion_frames(
        graphs,
        ranked_primary_hashes,
        edge_by_id,
        node_label,
        is_verbalizable_hash,
        limit_per_node=4,
    )
    if not _has_informative_conclusion_frames(frames):
        return SurfaceGraphSection()

    frame_hashes = _frame_scoped_hashes(frames, node_map)
    primary_hashes = [
        address_hash for address_hash in ranked_primary_hashes
        if address_hash in frame_hashes
    ]
    supporting_hashes = _rank_supporting_hashes(
        graphs,
        primary_hashes,
        node_map,
        node_label,
        is_verbalizable_hash,
        display_degree,
        limit=7,
    )
    supporting_hashes = [address_hash for address_hash in supporting_hashes if address_hash in frame_hashes]
    return SurfaceGraphSection(
        speaker="system",
        usage="Reasoned conclusion graph selected by the thinking loop. Prefer this over raw input or search when forming the answer.",
        focus=SurfaceFocus(
            primary=[node_label(h) for h in primary_hashes],
            supporting=[node_label(h) for h in supporting_hashes],
        ),
        frames=frames,
    )


def _build_search_graph_section(
    conclusion: "ConclusionView",
    node_map: dict[str, "Node"],
    node_label,
    is_verbalizable_hash,
    display_degree,
) -> SurfaceGraphSection:
    search_hashes = {h for h in conclusion.search_node_hashes if is_verbalizable_hash(h)}
    if not search_hashes:
        return SurfaceGraphSection()

    primary_hashes = _rank_fallback_hashes(
        search_hashes,
        conclusion.keyword_scores,
        node_map,
        node_label,
        is_verbalizable_hash,
        display_degree,
        limit=5,
    )

    supporting_candidates: set[str] = set()
    search_edges: list["Edge"] = []
    for edge in conclusion.edges:
        if edge.is_temporary or edge.provenance_source != "search":
            continue
        if edge.source_hash not in search_hashes and edge.target_hash not in search_hashes:
            continue
        if not is_verbalizable_hash(edge.source_hash) or not is_verbalizable_hash(edge.target_hash):
            continue
        search_edges.append(edge)
        supporting_candidates.add(edge.source_hash)
        supporting_candidates.add(edge.target_hash)

    supporting_hashes = _rank_fallback_hashes(
        supporting_candidates - set(primary_hashes),
        conclusion.keyword_scores,
        node_map,
        node_label,
        is_verbalizable_hash,
        display_degree,
        limit=7,
    )
    frames = _build_edge_scoped_frames(
        primary_hashes,
        search_edges,
        node_label,
        role="search",
        limit_per_node=5,
    )
    return SurfaceGraphSection(
        speaker="external",
        usage="Search-derived support graph. Use only as supporting evidence and never as the assistant's own identity or direct first-person claim.",
        focus=SurfaceFocus(
            primary=[node_label(h) for h in primary_hashes],
            supporting=[node_label(h) for h in supporting_hashes],
        ),
        frames=frames,
    )


def _build_input_frames(
    translated: TranslatedGraph,
    node_map: dict[str, "Node"],
    node_label,
    is_verbalizable_hash,
    primary_hashes: list[str],
) -> list[SurfaceNodeFrame]:
    edge_map: dict[str, list[SurfaceEdge]] = {}
    for edge in translated.edges:
        src_hash = _resolve_translated_ref_hash(edge.source_ref, node_map)
        tgt_hash = _resolve_translated_ref_hash(edge.target_ref, node_map)
        if src_hash is None or tgt_hash is None:
            continue
        if not is_verbalizable_hash(src_hash) or not is_verbalizable_hash(tgt_hash):
            continue
        edge_map.setdefault(src_hash, []).append(
            SurfaceEdge(
                target=node_label(tgt_hash),
                edge_family=edge.edge_family,
                connect_type=edge.connect_type,
                direction="out",
                weight=round(edge.confidence, 3),
                trust=round(edge.confidence, 3),
                support=0,
                score=round(edge.confidence, 3),
            )
        )

    frames: list[SurfaceNodeFrame] = []
    source_hashes = primary_hashes or sorted(edge_map.keys(), key=node_label)[:5]
    for source_hash in source_hashes:
        edges = edge_map.get(source_hash, [])
        frames.append(SurfaceNodeFrame(source=node_label(source_hash), role="input", edges=edges[:4]))
    return _dedupe_frames(frames)


def _resolve_translated_ref_hash(ref: "ConceptRef", node_map: dict[str, "Node"]) -> str | None:
    if isinstance(ref, ConceptPointer):
        return ref.address_hash
    if isinstance(ref, EmptySlot):
        address_hash = compute_hash(ref.concept_hint.strip())
        if address_hash in node_map:
            return address_hash
    return None


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
    ranked = _rank_hashes(hashes, node_map, node_label, is_verbalizable_hash, display_degree, limit=limit * 2)
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
    for address_hash in sorted(
        (value for value in hashes if is_verbalizable_hash(value)),
        key=lambda value: (-display_degree(value), node_label(value), value),
    ):
        node = node_map.get(address_hash)
        if node and (node.is_abstract or not node.labels):
            continue
        label = node_label(address_hash)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        ranked.append(address_hash)
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
            edges = _surface_edges_from_graph(
                source_hash,
                graph,
                edge_by_id,
                node_label,
                is_verbalizable_hash,
                limit=limit_per_node,
            )
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
        if not _is_surface_body_edge(edge):
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


def _build_edge_scoped_frames(
    primary_hashes: list[str],
    edges: list["Edge"],
    node_label,
    *,
    role: str,
    limit_per_node: int,
) -> list[SurfaceNodeFrame]:
    frames: list[SurfaceNodeFrame] = []
    for source_hash in primary_hashes:
        scoped: list[SurfaceEdge] = []
        for edge in edges:
            if source_hash not in {edge.source_hash, edge.target_hash}:
                continue
            scoped.append(_to_surface_edge(source_hash, edge, node_label, edge.edge_weight))
        scoped.sort(key=lambda item: (-item.score, -item.weight, item.target))
        frames.append(SurfaceNodeFrame(source=node_label(source_hash), role=role, edges=scoped[:limit_per_node]))
    return _dedupe_frames(frames)


def _is_surface_body_edge(edge: "Edge") -> bool:
    return edge.edge_family == "relation" and edge.connect_type != "neutral"


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
    for address_hash in sorted(hashes, key=lambda value: node_label(value)):
        if not is_verbalizable_hash(address_hash):
            continue
        label = node_label(address_hash)
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


def _has_informative_conclusion_frames(frames: list[SurfaceNodeFrame]) -> bool:
    return any(frame.edges for frame in frames)


def _frame_scoped_hashes(
    frames: list[SurfaceNodeFrame],
    node_map: dict[str, "Node"],
) -> set[str]:
    labels = {frame.source for frame in frames}
    for frame in frames:
        labels.update(edge.target for edge in frame.edges)

    hashes: set[str] = set()
    for address_hash, node in node_map.items():
        if node.labels and node.labels[0] in labels:
            hashes.add(address_hash)
    return hashes
