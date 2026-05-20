"""ThoughtEngine — Think 루프 실행기.

파이프라인:
  TranslatedGraph + 목표 노드
    → TempThoughtGraph 구성
    → Think 루프 (수렴까지)
        ├── ConceptDifferentiation
        ├── 필요 시 검색 (EmptySlot 존재 | 근거 부족)
        └── 수렴 판단 (patch overlap + goal alignment score)
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
    get_edges_for_node as db_get_edges_for_node,
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
from ...tools.search_client import SearchBundle, SearchResult
from ... import config
from . import concept_differentiation, concept_merge, goal_alignment, surface_variant_evidence
from .activation import build_activation_conclusion_graphs
from .claim_graph import AssertionState, apply_claim_conflict_pressure, build_claim_conflict_graph
from .conclusion_graph import ConclusionGraph, RejectedConclusionGraph
from .graph_patch import GraphPatch, patch_overlap_ratio
from .search_relation_extractor import RelationCandidate, extract_relation_candidates
from .temp_thought_graph import TempThoughtGraph


EmbedFn = Callable[[str], Awaitable[list[float]]]
SearchFn = Callable[[str], Awaitable[SearchBundle]]
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
    keyword_scores: dict[str, float] = field(default_factory=dict)
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
        existing = _find_matching_committed_edge(conn, edge)
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


def _find_matching_committed_edge(conn: sqlite3.Connection, edge: Edge) -> Edge | None:
    # Keep multi-relations between same endpoints distinct by semantic predicate.
    for existing in db_get_edges_for_node(conn, edge.source_hash, active_only=True):
        if existing.source_hash != edge.source_hash or existing.target_hash != edge.target_hash:
            continue
        if existing.edge_family != edge.edge_family:
            continue
        if existing.connect_type != edge.connect_type:
            continue
        if existing.proposed_connect_type != edge.proposed_connect_type:
            continue
        return existing
    return None


def _has_converged(
    tg: TempThoughtGraph,
    prev_node_count: int,
    prev_edge_count: int,
    previous_patches: list[GraphPatch],
    *,
    previous_goal_score: float | None,
    current_goal_score: float,
) -> bool:
    delta = tg.current_delta()
    if delta.is_empty():
        return True

    goal_delta = current_goal_score if previous_goal_score is None else current_goal_score - previous_goal_score
    goal_is_improving = goal_delta >= config.THINK_GOAL_SCORE_MIN_DELTA

    current_patches = tg.current_patches()
    if current_patches and previous_patches:
        overlap = patch_overlap_ratio(previous_patches, current_patches)
        if overlap >= PATCH_CONVERGENCE_OVERLAP_RATIO and not goal_is_improving:
            print(
                f"[think] patch_converged overlap={overlap:.2f} "
                f"goal_delta={goal_delta:.4f} goal_score={current_goal_score:.4f}"
            )
            return True

    unchanged_size = len(tg.all_nodes()) == prev_node_count and len(tg.all_edges()) == prev_edge_count
    if unchanged_size and not goal_is_improving:
        print(
            f"[think] size_converged goal_delta={goal_delta:.4f} "
            f"goal_score={current_goal_score:.4f}"
        )
        return True
    return False


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


def _search_query_from_slots(
    slots: list[EmptySlot],
    user_input: str | None,
) -> tuple[str | None, list[EmptySlot]]:
    """EmptySlot 중요도 구조에서 검색 쿼리 후보를 만든다.

    안정화 단계에서는 모든 EmptySlot을 검색하지 않는다. 낮은 근거의 단일 토큰 검색은
    잡음이 크므로, 중요도 상위 슬롯을 묶은 대표 쿼리 1개만 만든다. 외부 정보가
    실제로 필요하다는 별도 판단은 후속 SearchNeed primitive에서 다룬다.
    """
    ordered_slots = [slot for slot in slots if slot.concept_hint.strip()]
    if not ordered_slots:
        return None, []

    ranked = sorted(ordered_slots, key=lambda slot: slot.importance, reverse=True)
    keep_count = min(4, max(1, int(len(ranked) * 0.50 + 0.9999)))
    selected = [slot for slot in ranked[:keep_count] if slot.importance >= 0.10]
    if not selected:
        return None, []

    if user_input and user_input.strip():
        return user_input.strip(), selected

    combined = " ".join(
        normalize_text(slot.concept_hint.strip())
        for slot in selected
        if normalize_text(slot.concept_hint.strip())
    )
    return (combined.strip() or None), selected


class ThoughtEngine:
    def __init__(
        self,
        conn: sqlite3.Connection,
        embed_fn: EmbedFn,
        search_fn: SearchFn,
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

        # GlobalGoalGraph를 현재 사고 그래프에 읽기 전용으로 로드한다.
        # TODO: TurnGoalView가 명시 구조로 생기면 이 위치에서 함께 로드/정렬한다.
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
        previous_goal_score: float | None = None
        search_node_hashes: set[str] = set()
        searched_queries: set[str] = set()
        no_slot_search_used = False

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
                    tg,
                    user_input=user_input,
                    concept_hashes=existing_cp_hashes,
                    model=model,
                    searched_queries=searched_queries,
                )
                search_node_hashes |= newly_searched
                _t0 = _t(f"fill_empty_slots (loop {loop_count})", _ts)
                _add_translated_edges(tg, translated.edges, _te_added_keys)
            elif (
                not no_slot_search_used
                and self._should_search_without_slots(tg, translated)
            ):
                _ts = time.perf_counter()
                newly_searched = await self._search_without_slots(
                    tg,
                    translated=translated,
                    user_input=user_input,
                    previous_key_hashes=previous_key_hashes,
                    model=model,
                    searched_queries=searched_queries,
                )
                no_slot_search_used = True
                search_node_hashes |= newly_searched
                _t0 = _t(f"search_without_slots (loop {loop_count})", _ts)

            _td = time.perf_counter()
            diff_results = concept_differentiation.run(tg)
            _t(f"concept_diff (loop {loop_count})", _td)

            _tsv = time.perf_counter()
            surface_variant_results = surface_variant_evidence.run(tg)
            if surface_variant_results:
                _t(f"surface_variant_evidence (x{len(surface_variant_results)}) (loop {loop_count})", _tsv)

            _tm = time.perf_counter()
            merge_count = concept_merge.run(tg)
            if merge_count > 0:
                _t(f"concept_merge (x{merge_count}) (loop {loop_count})", _tm)

            for result in diff_results:
                _commit_weak(self._conn, result.abstract_node)
                for edge in result.edges_added:
                    _commit_edge(self._conn, edge, strong=False)

            goal_snapshot = goal_alignment.score_goal_alignment(
                tg,
                translated,
                conn=self._conn,
                previous_key_hashes=previous_key_hashes,
            )
            print(
                f"[think] goal_score={goal_snapshot.score:.4f} "
                f"aligned={goal_snapshot.aligned_count} "
                f"inputs={goal_snapshot.input_count} goals={goal_snapshot.goal_count}"
            )

            current_loop_patches = tg.current_patches()
            if _has_converged(
                tg,
                prev_node_count,
                prev_edge_count,
                prev_loop_patches,
                previous_goal_score=previous_goal_score,
                current_goal_score=goal_snapshot.score,
            ):
                break
            previous_goal_score = goal_snapshot.score
            prev_loop_patches = current_loop_patches
            prev_node_count = len(tg.all_nodes())
            prev_edge_count = len(tg.all_edges())

        concept_differentiation.run(tg)

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
        primary_scored = scored_direct + scored_slots
        key_hashes: set[str] = {h for _, h in primary_scored}
        ref_hashes: set[str] = {h for _, h in scored_context if h not in key_hashes}
        keyword_scores: dict[str, float] = {}
        for importance, h in primary_scored + scored_context:
            keyword_scores[h] = max(keyword_scores.get(h, 0.0), importance)
        if previous_key_hashes:
            ref_hashes |= (previous_key_hashes - key_hashes)
            for h in previous_key_hashes:
                keyword_scores.setdefault(h, 0.25)

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
            goal_hash=tg.goal_hash,
            had_empty_slots=had_empty_slots,
            loop_count=loop_count,
            topic_continuity=topic_continuity,
            model=model,
            user_input=user_input,
            key_hashes=key_hashes,
            ref_hashes=ref_hashes,
            keyword_scores=keyword_scores,
            search_node_hashes=search_node_hashes,
            selected_graphs=selected_graphs,
            rejected_graphs=activation_result.rejected_graphs,
            profile_activation_view=profile_activation_view,
        )

    def _add_search_result_edges(self, tg: TempThoughtGraph, search_text: str) -> None:
        from ..translation.token_splitter import extract_tokens
        from ..utils.hash_resolver import normalize_text
        tokens = extract_tokens(search_text)
        if not tokens:
            return

        mentioned: list[str] = []
        seen_hashes: set[str] = set()
        for token in tokens:
            normalized = normalize_text(token)
            for word_entry in get_words_for_surface(self._conn, normalized):
                h = word_entry.address_hash
                if h in seen_hashes or tg.get_node(h) is None:
                    continue
                seen_hashes.add(h)
                mentioned.append(h)

        if len(mentioned) < 2:
            return

        now = datetime.now(timezone.utc)
        added_keys: set[tuple[str, str]] = set()
        for i, src_hash in enumerate(mentioned):
            for tgt_hash in mentioned[i + 1:]:
                key = (src_hash, tgt_hash)
                if key in added_keys:
                    continue
                added_keys.add(key)
                tg.add_edge(Edge(
                    edge_id=str(uuid.uuid4()),
                    source_hash=src_hash,
                    target_hash=tgt_hash,
                    edge_family="concept",
                    connect_type="neutral",
                    edge_weight=0.5,
                    provenance_source="search",
                    proposed_connect_type="co_occurrence",
                    proposal_reason="검색 결과에서 함께 등장한 기존 개념",
                    is_temporary=False,
                    created_at=now,
                    updated_at=now,
                ))

    def _search_results_text(self, results: list[SearchResult]) -> str | None:
        if not results:
            return None
        parts: list[str] = []
        for item in results:
            if item.title:
                parts.append(f"{item.title}. {item.snippet}")
            else:
                parts.append(item.snippet)
        text = " ".join(parts).strip()
        return text or None

    def _seed_concept_labels(self, tg: TempThoughtGraph, concept_hashes: set[str] | None) -> list[str]:
        if not concept_hashes:
            return []
        labels: list[str] = []
        seen: set[str] = set()
        for address_hash in sorted(concept_hashes):
            node = tg.get_node(address_hash) or db_get_node(self._conn, address_hash)
            if node is None:
                continue
            label = node.primary_label().strip()
            if not label or label in seen:
                continue
            seen.add(label)
            labels.append(label)
        return labels

    async def _apply_search_relations(
        self,
        tg: TempThoughtGraph,
        *,
        query: str,
        relation_candidates: list[RelationCandidate],
    ) -> set[str]:
        touched_hashes: set[str] = set()
        for candidate in relation_candidates:
            subject_node = await self._resolve_or_create_concept_node(tg, candidate.subject)
            object_node = await self._resolve_or_create_concept_node(tg, candidate.object)

            touched_hashes.add(subject_node.address_hash)
            touched_hashes.add(object_node.address_hash)
            if subject_node.address_hash == object_node.address_hash:
                continue

            self._upsert_search_relation_edge(
                tg,
                query=query,
                candidate=candidate,
                source_hash=subject_node.address_hash,
                target_hash=object_node.address_hash,
            )
        return touched_hashes

    async def _resolve_or_create_concept_node(self, tg: TempThoughtGraph, label: str) -> Node:
        normalized = normalize_text(label.strip())
        if not normalized:
            raise RuntimeError("relation candidate label must not be empty")

        for word_entry in get_words_for_surface(self._conn, normalized):
            existing = db_get_node(self._conn, word_entry.address_hash)
            if existing is None or not existing.is_active:
                continue
            if tg.get_node(existing.address_hash) is None:
                tg.add_node(existing)
            return existing

        address_hash = compute_hash(label)
        existing_by_hash = db_get_node(self._conn, address_hash)
        if existing_by_hash is not None and existing_by_hash.is_active:
            if tg.get_node(existing_by_hash.address_hash) is None:
                tg.add_node(existing_by_hash)
            return existing_by_hash

        embedding = await self._embed_fn(label)
        now = datetime.now(timezone.utc)
        node = Node(
            address_hash=address_hash,
            node_kind="concept",
            formation_source="search",
            labels=[label.strip()],
            is_abstract=False,
            trust_score=0.35,
            stability_score=0.2,
            is_active=True,
            embedding=embedding,
            payload={},
            created_at=now,
            updated_at=now,
        )
        insert_node(self._conn, node)
        if not word_link_exists(self._conn, normalized, address_hash):
            insert_word(self._conn, WordEntry(
                word_id=str(uuid.uuid4()),
                surface_form=normalized,
                address_hash=address_hash,
                language=None,
                created_at=now,
            ))
        self._conn.commit()
        tg.add_node(node)
        return node

    def _upsert_search_relation_edge(
        self,
        tg: TempThoughtGraph,
        *,
        query: str,
        candidate: RelationCandidate,
        source_hash: str,
        target_hash: str,
    ) -> None:
        for edge in tg.get_edges_for_node(source_hash):
            if edge.source_hash != source_hash or edge.target_hash != target_hash:
                continue
            if edge.edge_family != "relation":
                continue
            if edge.connect_type != candidate.connect_type:
                continue
            if edge.proposed_connect_type != candidate.predicate:
                continue
            edge.support_count += 1
            edge.edge_weight = min(1.0, edge.edge_weight + (candidate.confidence - edge.edge_weight) * 0.5)
            edge.trust_score = min(1.0, max(edge.trust_score, 0.35 + candidate.confidence * 0.25))
            edge.proposal_reason = candidate.evidence
            edge.payload = self._merge_search_relation_payload(edge.payload, query, candidate)
            edge.touch()
            tg.update_edge(edge)
            return

        confidence = max(0.0, min(1.0, candidate.confidence))
        now = datetime.now(timezone.utc)
        tg.add_edge(Edge(
            edge_id=str(uuid.uuid4()),
            source_hash=source_hash,
            target_hash=target_hash,
            edge_family="relation",
            connect_type=candidate.connect_type,
            edge_weight=max(0.2, confidence),
            support_count=1,
            provenance_source="search",
            proposed_connect_type=candidate.predicate,
            proposal_reason=candidate.evidence,
            trust_score=0.35 + confidence * 0.25,
            payload=self._merge_search_relation_payload({}, query, candidate),
            is_temporary=False,
            created_at=now,
            updated_at=now,
        ))

    def _merge_search_relation_payload(
        self,
        payload: dict,
        query: str,
        candidate: RelationCandidate,
    ) -> dict:
        merged = dict(payload)
        merged["query"] = query
        merged["extractor"] = "search_relation_extractor_v1"
        evidences = list(merged.get("evidences") or [])
        if candidate.evidence not in evidences:
            evidences.append(candidate.evidence)
        merged["evidences"] = evidences[-5:]

        source_entry = {
            "title": candidate.source_title,
            "url": candidate.source_url,
        }
        sources = list(merged.get("sources") or [])
        if source_entry not in sources:
            sources.append(source_entry)
        merged["sources"] = sources[-8:]
        return merged

    def _should_search_without_slots(self, tg: TempThoughtGraph, translated: TranslatedGraph) -> bool:
        if tg.has_empty_slots():
            return False
        if len(translated.edges) < 2:
            return False
        focus_hashes = self._focus_hashes_from_translated(tg, translated)
        if not focus_hashes:
            return False
        return not self._has_non_neutral_relation_support(tg, focus_hashes)

    def _focus_hashes_from_translated(self, tg: TempThoughtGraph, translated: TranslatedGraph) -> set[str]:
        hashes: set[str] = set()
        if translated.input_bundle is not None:
            hashes |= set(translated.input_bundle.direct_hashes)
            hashes |= set(translated.input_bundle.center_hashes)
        for ref in translated.nodes:
            if isinstance(ref, ConceptPointer):
                hashes.add(ref.address_hash)
            elif isinstance(ref, EmptySlot):
                h = compute_hash(ref.concept_hint.strip())
                if tg.get_node(h) is not None:
                    hashes.add(h)
        return {h for h in hashes if tg.get_node(h) is not None}

    def _has_non_neutral_relation_support(self, tg: TempThoughtGraph, focus_hashes: set[str]) -> bool:
        for address_hash in focus_hashes:
            for edge in tg.get_edges_for_node(address_hash):
                if edge.is_temporary:
                    continue
                if edge.edge_family != "relation":
                    continue
                if edge.connect_type == "neutral":
                    continue
                return True
        return False

    def _plan_search_query_without_slots(
        self,
        tg: TempThoughtGraph,
        translated: TranslatedGraph,
        *,
        user_input: str | None,
        previous_key_hashes: set[str] | None,
    ) -> str | None:
        if not user_input or not user_input.strip():
            return None

        focus_labels_from_input = self._focus_labels_by_importance(translated, tg, limit=2)
        if focus_labels_from_input:
            # Prefer the most central focus label to avoid noisy phrase queries.
            return focus_labels_from_input[0]

        weak_input = self._is_weak_input_bundle(translated)
        if weak_input:
            context_labels = self._labels_from_hashes(tg, previous_key_hashes or set(), limit=2)
            if context_labels:
                return " ".join(context_labels)

        focus_labels = self._labels_from_hashes(
            tg,
            self._focus_hashes_from_translated(tg, translated),
            limit=2,
        )
        if focus_labels:
            return focus_labels[0]
        return user_input.strip()

    def _focus_labels_by_importance(
        self,
        translated: TranslatedGraph,
        tg: TempThoughtGraph,
        *,
        limit: int,
    ) -> list[str]:
        scored: list[tuple[float, str]] = []
        for ref in translated.nodes:
            if isinstance(ref, ConceptPointer):
                node = tg.get_node(ref.address_hash)
                if node is None:
                    continue
                label = node.primary_label().strip()
                if not label:
                    continue
                scored.append((ref.importance, label))
            elif isinstance(ref, EmptySlot):
                hint = ref.concept_hint.strip()
                if not hint:
                    continue
                h = compute_hash(hint)
                if tg.get_node(h) is None:
                    continue
                scored.append((ref.importance, hint))

        scored.sort(key=lambda item: item[0], reverse=True)
        labels: list[str] = []
        seen: set[str] = set()
        for _, label in scored:
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    def _labels_from_hashes(self, tg: TempThoughtGraph, hashes: set[str], *, limit: int) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for address_hash in sorted(hashes):
            node = tg.get_node(address_hash) or db_get_node(self._conn, address_hash)
            if node is None:
                continue
            label = node.primary_label().strip()
            if not label or label in seen:
                continue
            seen.add(label)
            labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    def _is_weak_input_bundle(self, translated: TranslatedGraph) -> bool:
        bundle = translated.input_bundle
        if bundle is not None:
            if bundle.direct_hashes:
                return False
            if bundle.sentence_edges:
                return False
            return True
        has_direct_pointer = any(
            isinstance(ref, ConceptPointer) and ref.is_direct_input_match
            for ref in translated.nodes
        )
        if has_direct_pointer:
            return False
        return len(translated.edges) == 0

    async def _search_without_slots(
        self,
        tg: TempThoughtGraph,
        *,
        translated: TranslatedGraph,
        user_input: str | None,
        previous_key_hashes: set[str] | None,
        model: str | None,
        searched_queries: set[str] | None,
    ) -> set[str]:
        query = self._plan_search_query_without_slots(
            tg,
            translated,
            user_input=user_input,
            previous_key_hashes=previous_key_hashes,
        )
        print(f"[think] no-slot search start  query={query!r}")
        if not query:
            return set()
        if searched_queries is not None and query in searched_queries:
            print(f"[think] no-slot search skip duplicate query={query!r}")
            return set()

        async def _run_query(query_text: str) -> SearchBundle | None:
            try:
                return await asyncio.wait_for(self._search_fn(query_text), timeout=config.SEARCH_TIMEOUT)
            except asyncio.TimeoutError:
                print(f"[think] search_fn timeout ({config.SEARCH_TIMEOUT}s) query={query_text!r}")
                return None

        _ts = time.perf_counter()
        search_bundle = await _run_query(query)
        _t("search_fn", _ts)
        if searched_queries is not None:
            searched_queries.add(query)

        search_results = search_bundle.results if search_bundle is not None else []
        if not search_results:
            return set()

        seed_concepts = self._labels_from_hashes(
            tg,
            self._focus_hashes_from_translated(tg, translated),
            limit=6,
        )
        relation_candidates = await extract_relation_candidates(
            user_input=user_input,
            query=query,
            search_results=search_results,
            seed_concepts=seed_concepts,
            model=model,
        )
        _tr = time.perf_counter()
        touched_hashes = await self._apply_search_relations(
            tg,
            query=query,
            relation_candidates=relation_candidates,
        )
        _t(f"search_relation_edges x{len(relation_candidates)}", _tr)

        search_text = self._search_results_text(search_results)
        if search_text:
            self._add_search_result_edges(tg, search_text)
        return touched_hashes

    async def _fill_empty_slots(
        self,
        tg: TempThoughtGraph,
        user_input: str | None = None,
        concept_hashes: set[str] | None = None,
        model: str | None = None,
        searched_queries: set[str] | None = None,
    ) -> set[str]:
        slots = list(tg.empty_slots)
        if not slots:
            return set()

        query, target_slots = _search_query_from_slots(slots, user_input)
        print(
            f"[think] search start  query={query!r}  slots={len(slots)} "
            f"target_slots={len(target_slots)}"
        )
        if not query or not target_slots:
            return set()
        if searched_queries is not None and query in searched_queries:
            print(f"[think] search skip duplicate query={query!r}")
            return set()

        async def _run_query(query_text: str) -> SearchBundle | None:
            try:
                return await asyncio.wait_for(self._search_fn(query_text), timeout=config.SEARCH_TIMEOUT)
            except asyncio.TimeoutError:
                print(f"[think] search_fn timeout ({config.SEARCH_TIMEOUT}s) query={query_text!r}")
                return None

        _ts = time.perf_counter()
        search_bundle = await _run_query(query)
        _t("search_fn", _ts)
        if searched_queries is not None:
            searched_queries.add(query)
        search_results = search_bundle.results if search_bundle is not None else []
        search_text = self._search_results_text(search_results)

        ingested_nodes: list[Node] = []
        session_search_hashes: set[str] = set()
        _ti = time.perf_counter()
        for slot in target_slots:
            node, got_search = await self._ingest_slot(slot, search_text=search_text)
            if node is not None:
                tg.fill_slot(slot, node)
                tg.connect_to_goal(node.address_hash)
                ingested_nodes.append(node)
                if got_search:
                    session_search_hashes.add(node.address_hash)
        _t(f"ingest_slots x{len(target_slots)}", _ti)

        if search_results:
            seed_concepts = self._seed_concept_labels(tg, concept_hashes)
            relation_candidates = await extract_relation_candidates(
                user_input=user_input,
                query=query,
                search_results=search_results,
                seed_concepts=seed_concepts,
                model=model,
            )
            _tr = time.perf_counter()
            touched_hashes = await self._apply_search_relations(
                tg,
                query=query,
                relation_candidates=relation_candidates,
            )
            session_search_hashes |= touched_hashes
            _t(f"search_relation_edges x{len(relation_candidates)}", _tr)

        if ingested_nodes:
            now = datetime.now(timezone.utc)
            for i, node_a in enumerate(ingested_nodes):
                for node_b in ingested_nodes[i + 1:]:
                    tg.add_edge(Edge(
                        edge_id=str(uuid.uuid4()),
                        source_hash=node_a.address_hash,
                        target_hash=node_b.address_hash,
                        edge_family="concept",
                        connect_type="neutral",
                        edge_weight=0.5,
                        provenance_source="search",
                        proposed_connect_type="co_occurrence",
                        proposal_reason="검색 컨텍스트에서 함께 등장한 개념",
                        is_temporary=False,
                        created_at=now,
                        updated_at=now,
                    ))
            if concept_hashes:
                for ingest_node in ingested_nodes:
                    for cp_hash in concept_hashes:
                        cp_node = tg.get_node(cp_hash)
                        if cp_node is None:
                            continue
                        tg.add_edge(Edge(
                            edge_id=str(uuid.uuid4()),
                            source_hash=cp_node.address_hash,
                            target_hash=ingest_node.address_hash,
                            edge_family="concept",
                            connect_type="neutral",
                            edge_weight=0.6,
                            provenance_source="search",
                            proposed_connect_type="co_occurrence",
                            proposal_reason="같은 쿼리에서 함께 등장한 개념",
                            is_temporary=False,
                            created_at=now,
                            updated_at=now,
                        ))

        if search_text:
            self._add_search_result_edges(tg, search_text)
        return session_search_hashes

    async def _ingest_slot(self, slot: EmptySlot, search_text: str | None = None) -> tuple[Node | None, bool]:
        _SUMMARY_MAX = 800
        hint = slot.concept_hint.strip()
        if not hint:
            return None, False

        address_hash = compute_hash(hint)
        existing = db_get_node(self._conn, address_hash)
        if existing is not None:
            if search_text and not existing.payload.get("search_summary"):
                existing.payload["search_summary"] = search_text[:_SUMMARY_MAX]
                existing.touch()
                update_node(self._conn, existing)
                self._conn.commit()
                return existing, True
            return existing, False

        embedding = await self._embed_fn(hint)

        payload: dict = {}
        if search_text:
            payload["search_summary"] = search_text[:_SUMMARY_MAX]

        now = datetime.now(timezone.utc)
        node = Node(
            address_hash=address_hash,
            node_kind="concept",
            formation_source="ingest",
            labels=[hint],
            is_abstract=False,
            trust_score=config.COMMIT_TRUST_WEAK,
            stability_score=config.COMMIT_STABILITY_WEAK,
            is_active=True,
            embedding=embedding,
            payload=payload,
            created_at=now,
            updated_at=now,
        )
        insert_node(self._conn, node)

        normalized = normalize_text(hint)
        if not word_link_exists(self._conn, normalized, address_hash):
            insert_word(self._conn, WordEntry(
                word_id=str(uuid.uuid4()),
                surface_form=normalized,
                address_hash=address_hash,
                language=None,
                created_at=now,
            ))

        self._conn.commit()
        return node, bool(search_text)

    def _commit_new_content(self, tg: TempThoughtGraph) -> None:
        merged_mappings = tg.merged_mappings
        if merged_mappings:
            for from_hash, to_hash in merged_mappings.items():
                remap_words_to_node(self._conn, [from_hash], to_hash)
                deactivate_node(self._conn, from_hash)

        for address_hash in tg.all_added_node_hashes:
            node = tg.get_node(address_hash)
            if node is None:
                continue
            if node.is_abstract:
                _commit_weak(self._conn, node)
            else:
                _commit_strong(self._conn, node)

        for edge_id in tg.all_added_edge_ids:
            edge = tg.get_edge(edge_id)
            if edge is None or edge.is_temporary:
                continue
            committed = _commit_edge(self._conn, edge, strong=True)
            _copy_committed_edge_state(edge, committed)

        self._conn.commit()


def _profile_subject_binding_hashes(profile_activation_view: ProfileActivationView | None) -> set[str]:
    """ClaimAssertion subject로 쓸 현재 사용자 identity surface 후보.

    문자열 패턴으로 이름을 추측하지 않고, 현재 입력과 UserProfile reference가 겹쳐
    ProfileActivationView에서 matched된 concept만 1차 subject binding 후보로 사용한다.
    """
    if profile_activation_view is None or not profile_activation_view.is_active:
        return set()
    return set(profile_activation_view.matched_hashes)
