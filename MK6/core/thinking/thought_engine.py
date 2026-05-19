"""ThoughtEngine — Think 루프 실행기.

파이프라인:
  TranslatedGraph + 목표 노드
    → TempThoughtGraph 구성
    → Think 루프 (수렴까지)
        ├── ConceptDifferentiation
        ├── 필요 시 검색 (EmptySlot 존재 | 근거 부족)
        └── 수렴 판단 (구조적 변화 감지)
    → ConclusionView 반환
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from ..entities.edge import Edge
from ..entities.node import Node
from ..entities.translated_graph import ConceptPointer, EmptySlot, TranslatedEdge, TranslatedGraph
from ..entities.word_entry import WordEntry
from ..profile import ProfileActivationView, attach_identity_surface_candidates, attach_profile_references
from ..storage.world_graph import (
    deactivate_node,
    get_edge as db_get_edge,
    get_edge_by_endpoints as db_get_edge_by_endpoints,
    get_node as db_get_node,
    get_words_for_surface,
    insert_edge,
    insert_node,
    insert_word,
    remap_words_to_node,
    update_edge,
    update_node,
    word_link_exists,
)
from ..utils.hash_resolver import compute_hash, normalize_text
from ..utils.local_graph_extractor import extract as extract_subgraph
from ... import config
from . import concept_differentiation, concept_merge
from .activation import build_activation_conclusion_graphs
from .claim_graph import AssertionState, apply_claim_conflict_pressure, build_claim_conflict_graph
from .conclusion_graph import ConclusionGraph, RejectedConclusionGraph
from .graph_patch import GraphPatch, patch_overlap_ratio
from .temp_thought_graph import TempThoughtGraph


EmbedFn = Callable[[str], Awaitable[list[float]]]
PATCH_CONVERGENCE_OVERLAP_RATIO = 0.5


def _t(label: str, start: float) -> float:
    elapsed = time.perf_counter() - start
    print(f"[think] {label}: {elapsed:.3f}s")
    return time.perf_counter()


@dataclass
class ConclusionView:
    """GraphToLang에 전달되는 결론 뷰.

    기존 호환 필드(nodes/edges/key_hashes/ref_hashes)는 유지한다. 다만 MK6의
    장기 계약에서 결론 본체는 node list가 아니라 selected_graphs에 담기는
    ConclusionGraph다.
    """

    nodes: list[Node]
    edges: list[Edge]
    goal_hash: str | None
    had_empty_slots: bool
    loop_count: int
    topic_continuity: str = "unknown"
    model: str | None = None
    user_input: str | None = None
    key_hashes: set[str] = field(default_factory=set)
    ref_hashes: set[str] = field(default_factory=set)
    search_node_hashes: set[str] = field(default_factory=set)
    selected_graphs: list[ConclusionGraph] = field(default_factory=list)
    rejected_graphs: list[RejectedConclusionGraph] = field(default_factory=list)
    profile_activation_view: ProfileActivationView | None = None


def _commit_strong(conn: sqlite3.Connection, node: Node) -> None:
    existing = db_get_node(conn, node.address_hash)
    if existing is None:
        insert_node(conn, node)
    else:
        node.touch()
        update_node(conn, node)


def _commit_weak(conn: sqlite3.Connection, node: Node) -> None:
    node.trust_score = min(node.trust_score, config.COMMIT_TRUST_WEAK)
    node.stability_score = min(node.stability_score, config.COMMIT_STABILITY_WEAK)
    node.touch()
    existing = db_get_node(conn, node.address_hash)
    if existing is None:
        insert_node(conn, node)
    else:
        update_node(conn, node)


def _copy_committed_edge_state(target: Edge, committed: Edge) -> None:
    """WorldGraph에 반영된 상태값을 현재 사고 그래프 edge에 되돌린다."""
    target.edge_weight = committed.edge_weight
    target.support_count = committed.support_count
    target.conflict_count = committed.conflict_count
    target.contradiction_pressure = committed.contradiction_pressure
    target.trust_score = committed.trust_score
    target.updated_at = committed.updated_at


def _commit_edge(conn: sqlite3.Connection, edge: Edge, strong: bool) -> Edge:
    """edge를 WorldGraph에 반영하고 최종 저장 상태를 반환한다.

    strong edge의 endpoint가 이미 WorldGraph에 존재하면 현재 사고 그래프의 병합된
    edge_weight와 세계 그래프 edge_weight 사이의 양의 차이 중 일부만 반영한다.
    """
    if not strong:
        edge.trust_score = min(edge.trust_score, config.COMMIT_TRUST_WEAK)
        edge.edge_weight = min(edge.edge_weight, 0.2)
    edge.is_temporary = False
    edge.touch()

    existing_by_id = db_get_edge(conn, edge.edge_id)
    if existing_by_id is not None:
        update_edge(conn, edge)
        return edge

    if strong:
        existing = db_get_edge_by_endpoints(conn, edge.source_hash, edge.target_hash)
        if existing is not None:
            diff = edge.edge_weight - existing.edge_weight
            if diff > 0:
                existing.edge_weight += diff * config.WORLD_EDGE_REINFORCE_ALPHA
            existing.support_count += max(1, edge.support_count + 1)
            existing.trust_score = max(existing.trust_score, edge.trust_score)
            existing.touch()
            update_edge(conn, existing)
            return existing

    insert_edge(conn, edge)
    return edge


def _has_converged(
    tg: TempThoughtGraph,
    prev_node_count: int,
    prev_edge_count: int,
    previous_patches: list[GraphPatch],
) -> bool:
    delta = tg.current_delta()
    if delta.is_empty():
        return True

    current_patches = tg.current_patches()
    if current_patches and previous_patches:
        overlap = patch_overlap_ratio(previous_patches, current_patches)
        if overlap >= PATCH_CONVERGENCE_OVERLAP_RATIO:
            print(f"[think] patch_converged overlap={overlap:.2f}")
            return True

    return len(tg.all_nodes()) == prev_node_count and len(tg.all_edges()) == prev_edge_count


def _load_subgraph_into_tg(tg: TempThoughtGraph, subgraph) -> None:
    """WorldGraph에서 읽은 LocalSubgraph를 TempThoughtGraph에 읽기 전용으로 적재한다."""
    for n in subgraph.nodes:
        if not tg.get_node(n.address_hash):
            tg._nodes[n.address_hash] = n
    for e in subgraph.edges:
        if e.edge_id not in tg._edges:
            tg._edges[e.edge_id] = e
            tg._adj.setdefault(e.source_hash, set()).add(e.target_hash)
            tg._adj.setdefault(e.target_hash, set()).add(e.source_hash)


def _add_translated_edges(
    tg: TempThoughtGraph,
    translated_edges: list[TranslatedEdge],
    added_keys: set[tuple[str, str]],
) -> None:
    now = datetime.now(timezone.utc)
    for te in translated_edges:
        if isinstance(te.source_ref, ConceptPointer):
            src_hash = te.source_ref.address_hash
        else:
            src_hash = compute_hash(te.source_ref.concept_hint.strip())
            if tg.get_node(src_hash) is None:
                continue

        if isinstance(te.target_ref, ConceptPointer):
            tgt_hash = te.target_ref.address_hash
        else:
            tgt_hash = compute_hash(te.target_ref.concept_hint.strip())
            if tg.get_node(tgt_hash) is None:
                continue

        key = (src_hash, tgt_hash)
        if key in added_keys:
            continue
        added_keys.add(key)
        tg.add_edge(Edge(
            edge_id=str(uuid.uuid4()),
            source_hash=src_hash,
            target_hash=tgt_hash,
            edge_family=te.edge_family,
            connect_type=te.connect_type,
            edge_weight=te.confidence,
            translation_confidence=te.confidence,
            provenance_source="lang_to_graph",
            proposed_connect_type=te.proposed_connect_type,
            is_temporary=False,
            created_at=now,
            updated_at=now,
        ))


def _search_queries_from_slots(slots: list[EmptySlot], user_input: str | None) -> list[str]:
    """EmptySlot 중요도 구조에서 검색 쿼리 후보를 만든다.

    안정화 단계에서는 모든 EmptySlot을 검색하지 않는다. 낮은 근거의 단일 토큰 검색은
    잡음이 크므로, 중요도 상위 슬롯을 묶은 대표 쿼리 1개만 만든다. 외부 정보가
    실제로 필요하다는 별도 판단은 후속 SearchNeed primitive에서 다룬다.
    """
    ordered_slots = [slot for slot in slots if slot.concept_hint.strip()]
    if not ordered_slots:
        return []

    ranked = sorted(ordered_slots, key=lambda slot: slot.importance, reverse=True)
    keep_count = min(3, max(1, int(len(ranked) * 0.25 + 0.9999)))
    selected = [slot for slot in ranked[:keep_count] if slot.importance >= 0.05]
    if not selected:
        return []

    combined = " ".join(slot.concept_hint.strip() for slot in selected)
    if not combined.strip():
        return []
    return [combined]


class ThoughtEngine:
    def __init__(
        self,
        conn: sqlite3.Connection,
        embed_fn: EmbedFn,
        search_fn: Callable[[str], Awaitable[str | None]],
        goal_node: Node,
    ) -> None:
        self._conn = conn
        self._embed_fn = embed_fn
        self._search_fn = search_fn
        self._goal_node = goal_node

    async def think(
        self,
        translated: TranslatedGraph,
        model: str | None = None,
        user_input: str | None = None,
        previous_key_hashes: set[str] | None = None,
        previous_assertion_state: AssertionState | None = None,
        profile_activation_view: ProfileActivationView | None = None,
    ) -> ConclusionView:
        _t0 = time.perf_counter()
        tg = TempThoughtGraph()
        tg.set_goal_node(self._goal_node)

        _load_subgraph_into_tg(tg, extract_subgraph(self._conn, self._goal_node.address_hash))

        tg.load_from_translated(translated)

        if profile_activation_view and profile_activation_view.is_active:
            for h in profile_activation_view.seed_hashes:
                if tg.get_node(h):
                    continue
                _load_subgraph_into_tg(tg, extract_subgraph(self._conn, h))

        if previous_key_hashes:
            for h in previous_key_hashes:
                if tg.get_node(h):
                    continue
                _load_subgraph_into_tg(tg, extract_subgraph(self._conn, h))

        if previous_assertion_state:
            for h in previous_assertion_state.node_hashes:
                if tg.get_node(h):
                    continue
                _load_subgraph_into_tg(tg, extract_subgraph(self._conn, h))

        _te_added_keys: set[tuple[str, str]] = set()
        _add_translated_edges(tg, translated.edges, _te_added_keys)

        from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER
        for ref in translated.nodes:
            if isinstance(ref, ConceptPointer):
                tg.connect_to_goal(ref.address_hash)
                if ref.is_direct_input_match:
                    tg.connect_to_identity(ref.address_hash, ANCHOR_USER)

        for anchor_h in [ANCHOR_USER, ANCHOR_ASSISTANT]:
            _load_subgraph_into_tg(tg, extract_subgraph(self._conn, anchor_h))

        _t0 = _t("graph init", _t0)
        had_empty_slots = tg.has_empty_slots()
        loop_count = 0
        prev_node_count = len(tg.all_nodes())
        prev_edge_count = len(tg.all_edges())
        prev_loop_patches: list[GraphPatch] = []
        search_node_hashes: set[str] = set()

        while loop_count < config.THINK_MAX_LOOPS:
            loop_count += 1
            tg.reset_delta()
            print(f"[think] loop {loop_count} start  nodes={len(tg.all_nodes())}  empty_slots={len(tg.empty_slots)}")

            if tg.has_empty_slots():
                _ts = time.perf_counter()
                existing_cp_hashes = {
                    ref.address_hash for ref in translated.nodes
                    if isinstance(ref, ConceptPointer) and ref.is_direct_input_match
                }
                newly_searched = await self._fill_empty_slots(
                    tg, user_input=user_input, concept_hashes=existing_cp_hashes
                )
                search_node_hashes |= newly_searched
                _t0 = _t(f"fill_empty_slots (loop {loop_count})", _ts)
                _add_translated_edges(tg, translated.edges, _te_added_keys)

            _td = time.perf_counter()
            diff_results = concept_differentiation.run(tg)
            _t(f"concept_diff (loop {loop_count})", _td)

            _tm = time.perf_counter()
            merge_count = concept_merge.run(tg)
            if merge_count > 0:
                _t(f"concept_merge (x{merge_count}) (loop {loop_count})", _tm)

            for result in diff_results:
                _commit_weak(self._conn, result.abstract_node)
                for edge in result.edges_added:
                    _commit_edge(self._conn, edge, strong=False)

            current_loop_patches = tg.current_patches()
            if _has_converged(tg, prev_node_count, prev_edge_count, prev_loop_patches):
                break
            prev_loop_patches = current_loop_patches
            prev_node_count = len(tg.all_nodes())
            prev_edge_count = len(tg.all_edges())

        concept_differentiation.run(tg)

        import math as _math
        scored_direct: list[tuple[float, str]] = []
        scored_context: list[tuple[float, str]] = []
        scored_slots: list[tuple[float, str]] = []
        for ref in translated.nodes:
            if isinstance(ref, ConceptPointer):
                h = ref.address_hash
                if tg.get_node(h) is None:
                    continue
                if ref.is_direct_input_match:
                    scored_direct.append((ref.importance, h))
                else:
                    scored_context.append((ref.importance, h))
            else:
                h = compute_hash(ref.concept_hint.strip())
                if tg.get_node(h) is not None:
                    scored_slots.append((ref.importance, h))

        scored_direct.sort(key=lambda x: x[0], reverse=True)
        scored_context.sort(key=lambda x: x[0], reverse=True)
        scored_slots.sort(key=lambda x: x[0], reverse=True)
        primary_scored = scored_direct or scored_slots
        n_sel = len(primary_scored)
        n_near = max(1, _math.ceil(n_sel * config.TOKEN_IMPORTANCE_NEAR_RATIO)) if n_sel else 0
        n_far = max(1, _math.ceil(n_sel * config.TOKEN_IMPORTANCE_FAR_RATIO)) if n_sel else 0
        key_hashes: set[str] = {h for _, h in primary_scored[:n_near]}
        far_cands: set[str] = {h for _, h in primary_scored[max(0, n_sel - n_far):]} if n_sel else set()
        ref_hashes: set[str] = far_cands - key_hashes
        if not scored_direct:
            ref_hashes |= {h for _, h in scored_context[:max(1, n_far or 1)]}
        if previous_key_hashes:
            ref_hashes |= (previous_key_hashes - key_hashes)

        if not previous_key_hashes:
            topic_continuity = "new_topic"
        else:
            overlap = len(key_hashes.intersection(previous_key_hashes))
            topic_continuity = "continued_topic" if overlap >= 2 else "related_topic" if overlap == 1 else "shifted_topic"

        _tc = time.perf_counter()
        tg.merge_duplicate_edges()
        self._commit_new_content(tg)
        _t("commit_new_content", _tc)

        profile_hashes = set(key_hashes) | set(ref_hashes)
        profile_hashes |= {ref.address_hash for ref in translated.nodes if isinstance(ref, ConceptPointer) and ref.is_direct_input_match}
        profile_hashes |= {compute_hash(ref.concept_hint.strip()) for ref in translated.nodes if isinstance(ref, EmptySlot)}
        attach_profile_references(self._conn, profile_hashes)

        subject_binding_hashes = _profile_subject_binding_hashes(profile_activation_view)
        if subject_binding_hashes:
            attach_identity_surface_candidates(self._conn, subject_binding_hashes)

        claim_conflict_graph, _claim_conflict = build_claim_conflict_graph(
            tg,
            translated,
            previous_assertion_state,
            subject_binding_hashes=subject_binding_hashes,
        )
        if claim_conflict_graph is not None:
            apply_claim_conflict_pressure(tg, previous_assertion_state)
            topic_continuity = "continued_topic"

        _ta = time.perf_counter()
        profile_context_hashes = profile_activation_view.seed_hashes if profile_activation_view else set()
        activation_result = build_activation_conclusion_graphs(
            tg,
            translated,
            conn=self._conn,
            previous_key_hashes=set(previous_key_hashes or set()) | set(profile_context_hashes),
        )
        _t("activation_conclusion_graphs", _ta)

        selected_graphs = list(activation_result.selected_graphs)
        if claim_conflict_graph is not None:
            selected_graphs.insert(0, claim_conflict_graph)

        return ConclusionView(
            nodes=tg.all_nodes(),
            edges=tg.all_edges(),