from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from ..entities.edge import Edge
from ..entities.translated_graph import ConceptPointer, EmptySlot, TranslatedGraph
from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER, compute_hash
from .conclusion_graph import ConclusionGraph, ReasoningPath, ReasoningStep
from .temp_thought_graph import TempThoughtGraph


AssertionSource = Literal["user", "assistant", "system", "search", "unknown"]
AssertionProvenance = Literal["user_statement", "assistant_statement", "system_policy", "search_result", "unknown"]


@dataclass(slots=True)
class ClaimAssertion:
    """발화/검색/시스템 정책에서 온 일반 주장 단위.

    self-claim, correction, preference, plan 같은 케이스별 그래프를 따로 만들지 않는다.
    그런 차이는 source/subject/object/provenance/temporal/conflict 구조에서 파생된다.
    """

    assertion_id: str
    source_hash: str
    source_role: AssertionSource
    subject_hashes: set[str] = field(default_factory=set)
    object_hashes: set[str] = field(default_factory=set)
    edge_ids: set[str] = field(default_factory=set)
    provenance: AssertionProvenance = "unknown"
    temporal_scope: str | None = None
    confidence: float = 0.7

    @property
    def node_hashes(self) -> set[str]:
        return {self.source_hash} | set(self.subject_hashes) | set(self.object_hashes)


@dataclass(slots=True)
class AssertionState:
    """직전 응답/현재 입력의 주장 상태 projection.

    텍스트가 아니라 key/ref/selected graph/claim assertion을 압축한 세션 상태다.
    assistant 전용이 아니다. 추후 user/search/system assertion history로 확장한다.
    """

    source_role: AssertionSource = "unknown"
    source_hash: str | None = None
    key_hashes: set[str] = field(default_factory=set)
    ref_hashes: set[str] = field(default_factory=set)
    selected_graphs: list[ConclusionGraph] = field(default_factory=list)
    assertions: list[ClaimAssertion] = field(default_factory=list)
    edge_ids: set[str] = field(default_factory=set)

    @property
    def node_hashes(self) -> set[str]:
        hashes = set(self.key_hashes) | set(self.ref_hashes)
        for graph in self.selected_graphs:
            hashes |= graph.node_hashes
        for assertion in self.assertions:
            hashes |= assertion.node_hashes
        return hashes


@dataclass(slots=True)
class ClaimConflict:
    """두 assertion projection 사이의 conflict 후보."""

    conflict_id: str
    current_assertion: ClaimAssertion
    previous_state: AssertionState
    edge_ids: set[str] = field(default_factory=set)
    conflict_paths: list[ReasoningPath] = field(default_factory=list)
    confidence: float = 0.7


def build_assertion_state_from_conclusion(conclusion, *, source_role: AssertionSource = "assistant") -> AssertionState:
    """ConclusionView에서 다음 턴 비교용 AssertionState를 만든다."""
    edge_ids: set[str] = set()
    for graph in conclusion.selected_graphs:
        edge_ids |= graph.edge_ids

    assertion = ClaimAssertion(
        assertion_id=_stable_hash("assertion::assistant::" + "|".join(sorted(conclusion.key_hashes | conclusion.ref_hashes))),
        source_hash=ANCHOR_ASSISTANT,
        source_role=source_role,
        subject_hashes=set(conclusion.key_hashes),
        object_hashes=set(conclusion.ref_hashes),
        edge_ids=edge_ids,
        provenance="assistant_statement",
        confidence=0.6,
    )

    return AssertionState(
        source_role=source_role,
        source_hash=ANCHOR_ASSISTANT,
        key_hashes=set(conclusion.key_hashes),
        ref_hashes=set(conclusion.ref_hashes),
        selected_graphs=list(conclusion.selected_graphs),
        assertions=[assertion],
        edge_ids=edge_ids,
    )


def build_user_assertion_from_translated(
    tg: TempThoughtGraph,
    translated: TranslatedGraph,
) -> ClaimAssertion | None:
    """현재 사용자 발화를 일반 ClaimAssertion으로 projection한다.

    사용자 자기진술을 별도 SelfClaimGraph로 만들지 않는다. source가 사용자이고,
    subject/object가 현재 입력 그래프에서 나온 일반 claim으로만 표현한다.

    TODO: subject binding 고도화
      - 사용자 identity/persona node가 안정화되면 subject_hashes를 ANCHOR_USER 또는
        USER_PERSON::<surface>로 resolve한다.
      - temporal_scope는 별도 Temporal/StateScope primitive로 옮긴다.
    """
    current_hashes = _translated_hashes(translated, tg)
    if not current_hashes:
        return None

    assertion_id = _stable_hash("assertion::user::" + "|".join(sorted(current_hashes)))
    return ClaimAssertion(
        assertion_id=assertion_id,
        source_hash=ANCHOR_USER,
        source_role="user",
        subject_hashes=set(current_hashes),
        object_hashes=set(),
        edge_ids=set(),
        provenance="user_statement",
        confidence=0.85,
    )


def build_claim_conflict_graph(
    tg: TempThoughtGraph,
    translated: TranslatedGraph,
    previous_state: AssertionState | None,
) -> tuple[ConclusionGraph | None, ClaimConflict | None]:
    """현재 사용자 claim과 직전 assertion state 사이의 conflict 후보를 만든다.

    CorrectionGraph를 별도 케이스 그래프로 만들지 않는다. 현재 사용자 assertion과
    직전 assertion state가 같은 국소 사고공간에 들어왔을 때 ClaimConflict를 만들고,
    그것을 conflict_paths를 가진 일반 ConclusionGraph로 projection한다.
    """
    if previous_state is None:
        return None, None

    current_assertion = build_user_assertion_from_translated(tg, translated)
    if current_assertion is None:
        return None, None

    current_hashes = set(current_assertion.subject_hashes | current_assertion.object_hashes)
    previous_hashes = {h for h in previous_state.node_hashes if tg.get_node(h) is not None}
    if not current_hashes or not previous_hashes:
        return None, None

    shared_hashes = current_hashes.intersection(previous_hashes)
    novel_hashes = current_hashes - previous_hashes
    adjacent_pairs = _current_previous_adjacency(tg, current_hashes, previous_hashes)

    if not shared_hashes and not adjacent_pairs:
        return None, None
    if not novel_hashes and not adjacent_pairs:
        return None, None

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
                proposed_connect_type="claim_conflict",
                proposal_reason="현재 사용자 assertion이 직전 assertion state와 구조적으로 충돌하는 후보",
                trust_score=0.8,
                edge_weight=0.8,
                is_temporary=True,
                payload={
                    "claim_conflict_candidate": True,
                    "current_assertion_id": current_assertion.assertion_id,
                    "previous_assertion_edge_ids": sorted(previous_state.edge_ids),
                },
                created_at=now,
                updated_at=now,
            )
            tg.add_edge(edge)
            conflict_edges.append(edge)

    if not conflict_edges:
        return None, None

    node_hashes = set(current_hashes) | related_previous | {ANCHOR_USER}
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

    conflict_id = _stable_hash(
        "claim-conflict::" + current_assertion.assertion_id + "::" + "|".join(sorted(edge_ids))
    )
    conflict = ClaimConflict(
        conflict_id=conflict_id,
        current_assertion=current_assertion,
        previous_state=previous_state,
        edge_ids=edge_ids,
        conflict_paths=conflict_paths,
        confidence=0.7,
    )

    graph_id = _stable_hash("claim-conflict-graph::" + conflict_id)
    graph = ConclusionGraph(
        graph_id=graph_id,
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
    return graph, conflict


def apply_claim_conflict_pressure(tg: TempThoughtGraph, previous_state: AssertionState | None) -> None:
    """직전 assertion state의 edge에 conflict pressure를 약하게 반영한다.

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


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
