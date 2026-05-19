from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass

from ... import config
from ..entities.edge import Edge
from ..entities.translated_graph import ConceptPointer, EmptySlot, TranslatedGraph
from ..goal import load_goal_view
from ..utils.hash_resolver import compute_hash
from . import relation_quality
from .conclusion_graph import (
    ActivationState,
    ConclusionGraph,
    ReasoningPath,
    ReasoningStep,
    RejectedConclusionGraph,
)
from .temp_thought_graph import TempThoughtGraph


@dataclass(frozen=True, slots=True)
class ActivationResult:
    """Think activation 결과 projection.

    실제 WorldGraph를 수정하지 않는다. 결론 그래프 생성을 위한 읽기 전용 결과다.
    """

    activation: dict[str, ActivationState]
    selected_graphs: list[ConclusionGraph]
    rejected_graphs: list[RejectedConclusionGraph]


def build_activation_conclusion_graphs(
    tg: TempThoughtGraph,
    translated: TranslatedGraph,
    *,
    conn,
    previous_key_hashes: set[str] | None = None,
    max_hops: int | None = None,
    graph_limit: int | None = None,
) -> ActivationResult:
    """input/goal 양방향 activation으로 ConclusionGraph skeleton을 만든다.

    주의:
    - 대부분의 `is_temporary=True` edge는 현재 턴의 view/귀속 연결이므로 결론
      근거나 goal support path로 사용하지 않는다.
    - 단, `view_scope=input_sentence` edge는 사용자 입력 자체를 이루는 국소그래프
      연결이므로 bounded activation 전파에만 사용한다.
    - restatement graph는 폐기하지 않고 rejected_graphs로 강등한다.
    - evidence/source node 분리는 아직 하지 않는다. # TODO: evidence/source 분리 후 support 재계산
    """
    max_hops = config.THINK_ACTIVATION_HOPS if max_hops is None else max_hops
    graph_limit = config.THINK_CONCLUSION_GRAPH_LIMIT if graph_limit is None else graph_limit

    input_sources = _translated_hashes(translated, tg)
    goal_sources = _goal_source_hashes(tg, conn)
    context_sources = {h for h in (previous_key_hashes or set()) if tg.get_node(h) is not None}

    input_paths = _spread(tg, input_sources, max_hops=max_hops)
    goal_paths = _spread(tg, goal_sources, max_hops=max_hops)
    context_paths = _spread(tg, context_sources, max_hops=max_hops)

    activation = _combine_activation(input_paths, goal_paths, context_paths, input_sources)
    selected, rejected = _build_conclusion_graphs(
        tg,
        input_sources=input_sources,
        goal_sources=goal_sources,
        input_paths=input_paths,
        goal_paths=goal_paths,
        activation=activation,
        graph_limit=graph_limit,
    )

    return ActivationResult(
        activation=activation,
        selected_graphs=selected,
        rejected_graphs=rejected,
    )


def _translated_hashes(translated: TranslatedGraph, tg: TempThoughtGraph) -> set[str]:
    hashes: set[str] = set()
    for ref in translated.nodes:
        if isinstance(ref, ConceptPointer):
            h = ref.address_hash
        elif isinstance(ref, EmptySlot):
            h = compute_hash(ref.concept_hint.strip())
        else:
            continue
        if tg.get_node(h) is not None:
            hashes.add(h)
    return hashes


def _goal_source_hashes(tg: TempThoughtGraph, conn) -> set[str]:
    hashes: set[str] = set()
    if tg.goal_hash and tg.get_node(tg.goal_hash) is not None:
        hashes.add(tg.goal_hash)

    goal_view = load_goal_view(conn)
    if goal_view is not None:
        for axis in goal_view.axis_refs:
            if tg.get_node(axis.node.address_hash) is not None:
                hashes.add(axis.node.address_hash)
    return hashes


def _spread(
    tg: TempThoughtGraph,
    source_hashes: set[str],
    *,
    max_hops: int,
) -> dict[str, ReasoningPath]:
    """source_hashes에서 bounded BFS로 가장 강한 ReasoningPath를 기록한다.

    목표/정체성 임시 연결은 현재 턴의 조회 view일 뿐, 결론 근거로 사용하면 입력
    토큰 전체가 goal-aligned로 오염된다. 반면 input_sentence runtime edge는
    사용자 입력 안에서 direct concept들이 어떤 국소 구조를 이루는지를 나타내므로
    activation 전파에는 사용한다.
    """
    best_paths: dict[str, ReasoningPath] = {}
    best_energy: dict[str, float] = {}
    queue: deque[tuple[str, ReasoningPath, float, int]] = deque()

    for h in source_hashes:
        path = ReasoningPath(start_hash=h, end_hash=h, steps=(), path_weight=1.0)
        best_paths[h] = path
        best_energy[h] = 1.0
        queue.append((h, path, 1.0, 0))

    while queue:
        current_hash, current_path, current_energy, depth = queue.popleft()
        if depth >= max_hops:
            continue

        for edge in tg.get_edges_for_node(current_hash):
            if not _can_spread_over(edge):
                continue

            next_hash, direction = _edge_next(edge, current_hash)
            if next_hash is None or tg.get_node(next_hash) is None:
                continue

            step_gain = _edge_gain(edge, direction=direction)
            if step_gain <= 0:
                continue

            next_energy = current_energy * step_gain * _depth_decay(depth + 1)
            if next_energy <= best_energy.get(next_hash, 0.0):
                continue

            step = ReasoningStep(
                source_hash=edge.source_hash,
                edge_id=edge.edge_id,
                target_hash=edge.target_hash,
                direction=direction,
                weight=next_energy,
            )
            next_path = ReasoningPath(
                start_hash=current_path.start_hash,
                end_hash=next_hash,
                steps=current_path.steps + (step,),
                path_weight=next_energy,
            )
            best_paths[next_hash] = next_path
            best_energy[next_hash] = next_energy
            queue.append((next_hash, next_path, next_energy, depth + 1))

    return best_paths


def _can_spread_over(edge: Edge) -> bool:
    if not edge.is_temporary:
        return True
    return edge.payload.get("view_scope") == "input_sentence"


def _edge_next(edge: Edge, current_hash: str) -> tuple[str | None, str]:
    if edge.source_hash == current_hash:
        return edge.target_hash, "forward"
    if edge.target_hash == current_hash:
        return edge.source_hash, "reverse"
    return None, "forward"


def _edge_gain(edge: Edge, *, direction: str) -> float:
    base = max(0.0, edge.edge_weight) * max(0.0, edge.trust_score)
    direction_gain = 1.0 if direction == "forward" else 0.55

    if edge.connect_type == "flow":
        connect_gain = 1.0
    elif edge.connect_type == "neutral":
        connect_gain = 0.65
    elif edge.connect_type == "opposite":
        connect_gain = 0.45
    elif edge.connect_type == "conflict":
        connect_gain = 0.35
    else:
        connect_gain = 0.5

    return base * direction_gain * connect_gain


def _depth_decay(depth: int) -> float:
    return 1.0 / max(1, depth)


def _combine_activation(
    input_paths: dict[str, ReasoningPath],
    goal_paths: dict[str, ReasoningPath],
    context_paths: dict[str, ReasoningPath],
    input_sources: set[str],
) -> dict[str, ActivationState]:
    hashes = set(input_paths) | set(goal_paths) | set(context_paths)
    result: dict[str, ActivationState] = {}
    for h in hashes:
        state = ActivationState(
            input_energy=input_paths.get(h).path_weight if h in input_paths else 0.0,
            goal_energy=goal_paths.get(h).path_weight if h in goal_paths else 0.0,
            context_energy=context_paths.get(h).path_weight if h in context_paths else 0.0,
            novelty_score=0.0 if h in input_sources else 1.0,
        )
        result[h] = state
    return result


def _build_conclusion_graphs(
    tg: TempThoughtGraph,
    *,
    input_sources: set[str],
    goal_sources: set[str],
    input_paths: dict[str, ReasoningPath],
    goal_paths: dict[str, ReasoningPath],
    activation: dict[str, ActivationState],
    graph_limit: int,
) -> tuple[list[ConclusionGraph], list[RejectedConclusionGraph]]:
    meeting_hashes = [
        h for h, state in activation.items()
        if state.input_energy > 0 and state.goal_energy > 0 and h not in goal_sources
    ]

    scored = sorted(
        meeting_hashes,
        key=lambda h: _candidate_score(h, activation[h], input_sources),
        reverse=True,
    )

    selected: list[ConclusionGraph] = []
    rejected: list[RejectedConclusionGraph] = []
    for h in scored:
        graph = _make_conclusion_graph(
            tg,
            core_hash=h,
            input_sources=input_sources,
            goal_sources=goal_sources,
            input_path=input_paths[h],
            goal_path=goal_paths[h],
            activation=activation,
        )
        quality = relation_quality.score_graph_relations(tg, graph)
        graph.score += quality.score
        graph.uncertainty = min(1.0, graph.uncertainty + quality.restatement_risk * 0.20)

        rejection_reason = _rejection_reason(graph, tg, quality=quality)
        if rejection_reason is not None:
            rejected.append(RejectedConclusionGraph(
                graph=graph,
                reason=rejection_reason,
                notes=["ConclusionGraph is kept for trace but not exposed to GraphToLang as selected context."],
            ))
            continue
        selected.append(graph)
        if len(selected) >= graph_limit:
            break

    selected.sort(key=lambda graph: graph.score, reverse=True)
    return selected, rejected


def _rejection_reason(graph: ConclusionGraph, tg: TempThoughtGraph, *, quality) -> str | None:
    if graph.is_likely_restatement:
        return "input_restatement"
    if not graph.edge_ids:
        return "insufficient_support"
    has_non_temporary_edge = any(
        (edge := tg.get_edge(edge_id)) is not None and not edge.is_temporary
        for edge_id in graph.edge_ids
    )
    if not has_non_temporary_edge:
        return "insufficient_support"
    if not graph.has_non_input_structure and not graph.exception_hashes and not graph.bridge_hashes:
        return "input_restatement"
    if quality.average_edge_score <= 0.0 or quality.support_strength <= 0.0:
        return "insufficient_support"
    if quality.restatement_risk >= 0.60 and quality.bridge_value < 0.10 and quality.goal_relevance < 0.20:
        return "input_restatement"
    if quality.goal_relevance <= 0.0 and quality.bridge_value <= 0.0 and not graph.has_conflict_structure:
        return "insufficient_goal_alignment"
    if graph.has_conflict_structure and quality.conflict_pressure > quality.support_strength:
        return "conflict_dominant"
    return None


def _candidate_score(core_hash: str, state: ActivationState, input_sources: set[str]) -> float:
    score = state.input_energy * state.goal_energy
    score += state.context_energy * 0.2
    score += state.novelty_score * 0.15
    if core_hash in input_sources:
        score *= 0.55
    score -= state.conflict_pressure * 0.3
    return score


def _make_conclusion_graph(
    tg: TempThoughtGraph,
    *,
    core_hash: str,
    input_sources: set[str],
    goal_sources: set[str],
    input_path: ReasoningPath,
    goal_path: ReasoningPath,
    activation: dict[str, ActivationState],
) -> ConclusionGraph:
    node_hashes = set(input_path.node_hashes) | set(goal_path.node_hashes) | {core_hash}
    edge_ids = set(input_path.edge_ids) | set(goal_path.edge_ids)
    conflict_paths: list[ReasoningPath] = []
    contrast_paths: list[ReasoningPath] = []
    exception_hashes: set[str] = set()

    for edge in tg.get_edges_for_node(core_hash):
        if edge.is_temporary:
            continue
        other_hash, direction = _edge_next(edge, core_hash)
        if other_hash is None:
            continue
        if edge.connect_type == "conflict":
            conflict_paths.append(_single_edge_path(core_hash, other_hash, edge, direction))
            exception_hashes.add(other_hash)
            node_hashes.add(other_hash)
            edge_ids.add(edge.edge_id)
            activation.setdefault(other_hash, ActivationState()).conflict_pressure += edge.edge_weight * edge.trust_score
        elif edge.connect_type == "opposite":
            contrast_paths.append(_single_edge_path(core_hash, other_hash, edge, direction))
            node_hashes.add(other_hash)
            edge_ids.add(edge.edge_id)

    bridge_hashes = node_hashes - {core_hash} - input_sources - goal_sources - exception_hashes
    support_paths = [input_path]
    goal_paths = [goal_path]

    graph_id = hashlib.sha256(
        (core_hash + "::" + "|".join(sorted(edge_ids))).encode("utf-8")
    ).hexdigest()[:32]

    score = _candidate_score(core_hash, activation.get(core_hash, ActivationState()), input_sources)
    if core_hash in input_sources:
        uncertainty = 0.35
    else:
        uncertainty = 0.15 + min(0.5, len(conflict_paths) * 0.1)

    return ConclusionGraph(
        graph_id=graph_id,
        input_hashes=set(input_sources),
        goal_hashes=set(goal_sources),
        node_hashes=node_hashes,
        edge_ids=edge_ids,
        core_hashes={core_hash},
        condition_hashes=set(),
        exception_hashes=exception_hashes,
        action_hashes=set(),
        bridge_hashes=bridge_hashes,
        support_paths=support_paths,
        goal_paths=goal_paths,
        conflict_paths=conflict_paths,
        contrast_paths=contrast_paths,
        score=score,
        uncertainty=uncertainty,
        activation={h: activation[h] for h in node_hashes if h in activation},
    )


def _single_edge_path(start_hash: str, end_hash: str, edge: Edge, direction: str) -> ReasoningPath:
    return ReasoningPath(
        start_hash=start_hash,
        end_hash=end_hash,
        steps=(ReasoningStep(edge.source_hash, edge.edge_id, edge.target_hash, direction=direction, weight=edge.edge_weight),),
        path_weight=edge.edge_weight * edge.trust_score,
    )
