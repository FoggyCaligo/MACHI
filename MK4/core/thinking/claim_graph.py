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
    *,
    subject_binding_hashes: set[str] | None = None,
) -> ClaimAssertion | None:
    """현재 사용자 발화를 일반 ClaimAssertion으로 projection한다.

    source는 항상 사용자다. subject는 가능하면 UserProfile identity surface 후보로 resolve된
    concept을 사용한다. 입력 concept projection은 현재 입력 direct match와 EmptySlot ingest만
    사용하고, semantic local candidate는 claim 본체가 아니라 주변 context 후보로 남긴다.
    """
    current_hashes = _translated_direct_hashes(translated, tg)
    if not current_hashes:
        return None

    binding_hashes = {h for h in (subject_binding_hashes or set()) if h in current_hashes and tg.get_node(h) is not None}
    subject_hashes = binding_hashes or set(current_hashes)
    object_hashes = set(current_hashes) - set(subject_hashes)

    assertion_id = _stable_hash(
        "assertion::user::"
        + "subjects=" + "|".join(sorted(subject_hashes))
        + "::objects=" + "|".join(sorted(object_hashes))
    )
    return ClaimAssertion(
        assertion_id=assertion_id,
        source_hash=ANCHOR_USER,
        source_role="user",
        subject_hashes=set(subject_hashes),
        object_hashes=object_hashes,
        edge_ids=set(),
        provenance="user_statement",
        confidence=0.9 if binding_hashes else 0.85,
    )


def build_claim_conflict_graph(
    tg: TempThoughtGraph,
    translated: TranslatedGraph,
    previous_state: AssertionState | None,
    *,
    subject_binding_hashes: set[str] | None = None,
) -> tuple[ConclusionGraph | None, ClaimConflict | None]:
    """현재 사용자 claim과 직전 assertion state 사이의 conflict 후보를 만든다.

    보수적 skeleton: 단순 shared node나 neutral adjacency만으로는 conflict를 만들지 않는다.
    이미 그래프 안에 conflict/opposite 구조가 있을 때만 ClaimConflict로 projection한다.
    """
    if previous_state is None:
        return None, None

    current_assertion = build_user_assertion_from_translated(
        tg,
        translated,
        subject_binding_hashes=subject_binding_hashes,
    )
    if current_assertion is None:
        return None, None

    current_hashes = set(current_assertion.subject_hashes | current_assertion.object_hashes)
    previous_hashes = {h for h in previous_state.node_hashes if tg.get_node(h) is not None}
    if not current_hashes or not previous_hashes:
        return None, None

    explicit_pairs = _current_previous_explicit_conflict_adjacency(tg, current_hashes, previous_hashes)
    if not explicit_pairs:
        return None, None

    now = datetime.now(timezone.utc)
    conflict_edges: list[Edge] = []
    core_hashes = {current for current, _ in explicit_pairs}
    related_previous = {previous for _, previous in explicit_pairs}
    shared_hashes = current_hashes.intersection(previous_hashes)

    for current_hash, previous_hash in sorted(explicit_pairs):
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
            proposal_reason="현재 사용자 assertion과 직전 assertion state 사이에 명시적 conflict/opposite 구조가 있는 후보",
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


def apply_user_correction_policy(
    tg: TempThoughtGraph,
    translated: TranslatedGraph,
    previous_state: AssertionState | None,
    *,
    subject_binding_hashes: set[str] | None = None,
) -> ClaimAssertion | None:
    """현재 사용자 assertion이 이전 assertion을 대체하는 구조를 world edge로 반영한다."""
    assertion = build_user_assertion_from_translated(
        tg,
        translated,
        subject_binding_hashes=subject_binding_hashes,
    )
    if assertion is None:
        return None

    replaced_hashes = _replaced_previous_object_hashes(
        tg,
        previous_state,
        assertion=assertion,
    )
    affirmed_hashes = set(assertion.object_hashes) - replaced_hashes

    if affirmed_hashes:
        _strengthen_user_assertion_edges(
            tg,
            assertion=assertion,
            target_hashes=affirmed_hashes,
        )

    if replaced_hashes:
        _upsert_user_conflict_edges(
            tg,
            assertion=assertion,
            target_hashes=replaced_hashes,
            previous_state=previous_state,
        )

    if previous_state is not None and replaced_hashes:
        _apply_previous_assertion_correction_pressure(
            tg,
            assertion=assertion,
            previous_state=previous_state,
            replaced_hashes=replaced_hashes,
        )

    return assertion


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


def _translated_direct_hashes(translated: TranslatedGraph, tg: TempThoughtGraph) -> set[str]:
    hashes: set[str] = set()
    for ref in translated.nodes:
        if isinstance(ref, ConceptPointer):
            if not ref.is_direct_input_match:
                continue
            h = ref.address_hash
        elif isinstance(ref, EmptySlot):
            h = compute_hash(ref.concept_hint.strip())
        else:
            continue
        if tg.get_node(h) is not None:
            hashes.add(h)
    return hashes


def _current_previous_explicit_conflict_adjacency(
    tg: TempThoughtGraph,
    current_hashes: set[str],
    previous_hashes: set[str],
) -> set[tuple[str, str]]:
    """current/previous 사이의 명시적 conflict/opposite 인접만 반환한다.

    neutral co-occurrence, shared topic, temporal continuation은 conflict의 충분조건이 아니다.
    """
    pairs: set[tuple[str, str]] = set()
    for current_hash in current_hashes:
        for edge in tg.get_edges_for_node(current_hash):
            if edge.is_temporary:
                continue
            if edge.connect_type not in {"conflict", "opposite"}:
                continue
            other = edge.target_hash if edge.source_hash == current_hash else edge.source_hash
            if other in previous_hashes:
                pairs.add((current_hash, other))
    return pairs


def _strengthen_user_assertion_edges(
    tg: TempThoughtGraph,
    *,
    assertion: ClaimAssertion,
    target_hashes: set[str],
) -> None:
    now = datetime.now(timezone.utc)
    for subject_hash in sorted(assertion.subject_hashes):
        if tg.get_node(subject_hash) is None:
            continue
        for target_hash in sorted(target_hashes):
            if target_hash == subject_hash or tg.get_node(target_hash) is None:
                continue
            existing = _find_matching_edge(
                tg,
                source_hash=subject_hash,
                target_hash=target_hash,
                connect_type="flow",
                proposed_connect_type="user_assertion",
            )
            if existing is not None:
                existing.support_count += 1
                existing.edge_weight = min(1.5, max(existing.edge_weight, 0.7) + 0.1)
                existing.trust_score = max(existing.trust_score, 0.8)
                existing.payload["last_assertion_id"] = assertion.assertion_id
                existing.payload["user_assertion"] = True
                existing.touch()
                tg.update_edge(existing)
                continue

            tg.add_edge(Edge(
                edge_id=str(uuid.uuid4()),
                source_hash=subject_hash,
                target_hash=target_hash,
                edge_family="relation",
                connect_type="flow",
                provenance_source="user_policy",
                proposed_connect_type="user_assertion",
                proposal_reason="현재 사용자 자기서술에서 함께 확인된 관계",
                support_count=1,
                trust_score=0.8,
                edge_weight=0.75,
                is_temporary=False,
                payload={
                    "user_assertion": True,
                    "assertion_id": assertion.assertion_id,
                },
                created_at=now,
                updated_at=now,
            ))


def _upsert_user_conflict_edges(
    tg: TempThoughtGraph,
    *,
    assertion: ClaimAssertion,
    target_hashes: set[str],
    previous_state: AssertionState | None,
) -> None:
    now = datetime.now(timezone.utc)
    previous_edge_ids = sorted(previous_state.edge_ids) if previous_state is not None else []
    for subject_hash in sorted(assertion.subject_hashes):
        if tg.get_node(subject_hash) is None:
            continue
        for target_hash in sorted(target_hashes):
            if target_hash == subject_hash or tg.get_node(target_hash) is None:
                continue
            existing = _find_matching_edge(
                tg,
                source_hash=subject_hash,
                target_hash=target_hash,
                connect_type="conflict",
                proposed_connect_type="user_correction_conflict",
            )
            if existing is not None:
                existing.support_count += 1
                existing.conflict_count += 1
                existing.edge_weight = min(1.5, max(existing.edge_weight, 0.8) + 0.1)
                existing.trust_score = max(existing.trust_score, 0.85)
                existing.payload["last_assertion_id"] = assertion.assertion_id
                existing.payload["user_correction"] = True
                existing.touch()
                tg.update_edge(existing)
                continue

            tg.add_edge(Edge(
                edge_id=str(uuid.uuid4()),
                source_hash=subject_hash,
                target_hash=target_hash,
                edge_family="relation",
                connect_type="conflict",
                provenance_source="user_policy",
                proposed_connect_type="user_correction_conflict",
                proposal_reason="현재 사용자 정정 입력과 충돌하는 이전 주장 후보",
                support_count=1,
                conflict_count=1,
                contradiction_pressure=0.8,
                trust_score=0.85,
                edge_weight=0.85,
                is_temporary=False,
                payload={
                    "user_correction": True,
                    "assertion_id": assertion.assertion_id,
                    "previous_assertion_edge_ids": previous_edge_ids,
                },
                created_at=now,
                updated_at=now,
            ))


def _apply_previous_assertion_correction_pressure(
    tg: TempThoughtGraph,
    *,
    assertion: ClaimAssertion,
    previous_state: AssertionState,
    replaced_hashes: set[str],
) -> None:
    for edge_id in previous_state.edge_ids:
        edge = tg.get_edge(edge_id)
        if edge is None or edge.is_temporary:
            continue

        edge_hashes = {edge.source_hash, edge.target_hash}
        if not (edge_hashes & replaced_hashes):
            continue

        edge.conflict_count += 1
        edge.contradiction_pressure += 0.65
        edge.trust_score = max(0.05, edge.trust_score * 0.55)
        edge.payload["corrected_by_user"] = True
        edge.payload["last_correction_assertion_id"] = assertion.assertion_id
        edge.touch()
        tg.update_edge(edge)

def _replaced_previous_object_hashes(
    tg: TempThoughtGraph,
    previous_state: AssertionState | None,
    *,
    assertion: ClaimAssertion,
) -> set[str]:
    if previous_state is None or not assertion.subject_hashes or not assertion.object_hashes:
        return set()

    replaced: set[str] = set()
    current_subjects = set(assertion.subject_hashes)
    current_objects = set(assertion.object_hashes)
    for previous_assertion in previous_state.assertions:
        if not (previous_assertion.subject_hashes & current_subjects):
            continue

        previous_objects = {
            address_hash
            for address_hash in previous_assertion.object_hashes
            if address_hash not in current_subjects and tg.get_node(address_hash) is not None
        }
        if not previous_objects:
            continue

        introduced_objects = current_objects - previous_objects
        if not introduced_objects:
            continue

        replaced |= previous_objects - introduced_objects
    return replaced


def _find_matching_edge(
    tg: TempThoughtGraph,
    *,
    source_hash: str,
    target_hash: str,
    connect_type: str,
    proposed_connect_type: str,
) -> Edge | None:
    for edge in tg.get_edges_for_node(source_hash):
        if edge.source_hash != source_hash or edge.target_hash != target_hash:
            continue
        if edge.connect_type != connect_type:
            continue
        if edge.proposed_connect_type != proposed_connect_type:
            continue
        return edge
    return None


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
