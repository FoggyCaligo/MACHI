from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..entities.edge import Edge
from ..entities.translated_graph import ConceptPointer, EmptySlot, TranslatedGraph
from ..utils.hash_resolver import compute_hash
from .conclusion_graph import ConclusionGraph, ReasoningPath, ReasoningStep
from .temp_thought_graph import TempThoughtGraph


@dataclass(slots=True)
class PreviousAssistantState:
    """직전 assistant 응답의 구조적 상태.

    텍스트가 아니라 직전 ConclusionView의 key/ref/selected graph를 압축한 세션 상태다.
    """

    key_hashes: set[str] = field(default_factory=set)
    ref_hashes: set[str] = field(default_factory=set)
    selected_graphs: list[ConclusionGraph] = field(default_factory=list)
    edge_ids: set[str] = field(default_factory=set)

    @property
    def node_hashes(self) -> set[str]:
        hashes = set(self.key_hashes) | set(self.ref_hashes)
        for graph in self.selected_graphs:
            hashes |= graph.node_hashes
        return hashes


def build_previous_assistant_state(conclusion) -> PreviousAssistantState:
    """ConclusionView에서 다음 턴 correction 비교용 상태를 만든다."""
    edge_ids: set[str] = set()
    for graph in conclusion.selected_graphs:
        edge_ids |= graph.edge_ids
    return PreviousAssistantState(
        key_hashes=set(conclusion.key_hashes),
        ref_hashes=set(conclusion.ref_hashes),
        selected_graphs=list(conclusion.selected_graphs),
        edge_ids=edge_ids,
    )


def build_correction_graph(
    tg: TempThoughtGraph,
    translated: TranslatedGraph,
    previous_state: PreviousAssistantState | None,
) -> ConclusionGraph | None:
    """직전 assistant assertion과 현재 사용자 입력 사이의 correction 후보를 만든다.

    문자열 패턴으로 정정 발화를 판별하지 않는다. 현재 입력 그래프가 직전 assistant
    상태와 같은 국소 사고공간에 들어왔고, 현재 입력이 새로운 구조를 추가했을 때만
    correction candidate를 만든다.

    이 함수는 WorldGraph를 직접 수정하지 않는다. 단, correction graph에 포함된
    conflict edge는 TempThoughtGraph에만 추가되어 GraphToLang/trace가 볼 수 있다.
    """
    if previous_state is None:
        return None

    current_hashes = _translated_hashes(translated, tg)
    previous_hashes = {h for h in previous_state.node_hashes if tg.get_node(h) is not None}
    if not current_hashes or not previous_hashes:
        return None

    shared_hashes = current_hashes.intersection(previous_hashes)
    novel_hashes = current_hashes - previous_hashes

    # 같은 노드를 직접 다시 언급했거나, 직전 assistant graph 근처에 현재 입력이 들어온 경우를
    # correction 후보로 본다. 단순 새 주제 전환을 줄이기 위해 shared 또는 adjacency를 요구한다.
    adjacent_pairs = _current_previous_adjacency(tg, current_hashes, previous_hashes)
    if not shared_hashes and not adjacent_pairs:
        return None

    # 현재 입력이 완전히 직전 상태 반복이면 correction으로 보지 않는다.
    if not novel_hashes and not adjacent_pairs:
        return None

    now = datetime.now(timezone.utc)
    conflict_edges: list[Edge] = []
    core_hashes = set(novel_hashes) if novel_hashes else set(shared_hashes)
    related_previous = set(shared_hashes)
    related_previous |= {p for _, p in adjacent_pairs}
    if not related_previous:
        related_previous = set(list(previous_hashes)[:3])

    for current_hash in sorted(core_hashes):
        for previous_hash in sorted(related_previous):
            if current_hash == previous_hash:
                continue
            edge = Edge(
                edge_id=str(uuid.uuid4()),
                source_hash=current_hash,
                target_hash=previous_hash,
                edge_family="relation",
                connect_type="conflict",
                provenance_source="user_policy",
                proposed_connect_type="user_correction",
                proposal_reason="현재 사용자 입력이 직전 assistant 상태와 구조적으로 충돌하는 correction 후보",
                trust_score=0.8,
                edge_weight=0.8,
                is_temporary=True,
                payload={
                    "correction_candidate": True,
                    "previous_assistant_edge_ids": sorted(previous_state.edge_ids),
                },
                created_at=now,
                updated_at=now,
            )
            tg.add_edge(edge)
            conflict_edges.append(edge)

    if not conflict_edges:
        return None

    node_hashes = set(current_hashes) | related_previous
    edge_ids = {edge.edge_id for edge in conflict_edges}
    conflict_paths = [
        ReasoningPath(
            start_hash=edge.source_hash,
            end_hash=edge.target_hash,
            steps=(ReasoningStep(edge.source_hash, edge.edge_id, edge.target_hash, weight=edge.edge_weight),),
            path_weight=edge.edge_weight * edge.trust_score,
        )
        for edge in conflict_edges
    ]

    graph_id = hashlib.sha256(
        ("correction::" + "|".join(sorted(node_hashes)) + "::" + "|".join(sorted(edge_ids))).encode("utf-8")
    ).hexdigest()[:32]

    return ConclusionGraph(
        graph_id=graph_id,
        graph_kind="correction",
        input_hashes=set(current_hashes),
        goal_hashes=set(),
        node_hashes=node_hashes,
        edge_ids=edge_ids,
        core_hashes=core_hashes,
        condition_hashes=set(related_previous),
        exception_hashes=set(related_previous),
        action_hashes=set(),
        bridge_hashes=set(shared_hashes),
        support_paths=[],
        goal_paths=[],
        conflict_paths=conflict_paths,
        contrast_paths=[],
        score=0.7,
        uncertainty=0.35,
        activation={},
    )


def apply_correction_pressure(tg: TempThoughtGraph, previous_state: PreviousAssistantState | None) -> None:
    """직전 assistant selected graph의 edge에 correction pressure를 약하게 반영한다.

    WorldGraph에는 직접 commit하지 않는다. 현재 TempThoughtGraph 안에서만 conflict_count와
    contradiction_pressure를 올려, 이후 Think/GraphToLang이 이전 assertion을 더 조심스럽게
    다루게 한다.
    """
    if previous_state is None:
        return
    for edge_id in previous_state.edge_ids:
        edge = tg.get_edge(edge_id)
        if edge is None or edge.is_temporary:
            continue
        edge.conflict_count += 1
        edge.contradiction_pressure += 0.4
        edge.trust_score = max(0.05, edge.trust_score * 0.75)
        edge.touch()
        tg.update_edge(edge)


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


def _current_previous_adjacency(
    tg: TempThoughtGraph,
    current_hashes: set[str],
    previous_hashes: set[str],
) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for current_hash in current_hashes:
        for edge in tg.get_edges_for_node(current_hash):
            if edge.is_temporary:
                continue
            other = edge.target_hash if edge.source_hash == current_hash else edge.source_hash
            if other in previous_hashes:
                pairs.add((current_hash, other))
    return pairs
