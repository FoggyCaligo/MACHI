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
from .temp_thought_graph import TempThoughtGraph


EmbedFn = Callable[[str], Awaitable[list[float]]]


def _t(label: str, start: float) -> float:
    """경과 시간을 출력하고 현재 시각을 반환한다."""
    elapsed = time.perf_counter() - start
    print(f"[think] {label}: {elapsed:.3f}s")
    return time.perf_counter()


@dataclass
class ConclusionView:
    """Think 루프 종료 후 GraphToLang에 전달되는 최종 구조."""

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


# ── 세계그래프 커밋 ───────────────────────────────────────────────────────────

def _commit_strong(conn: sqlite3.Connection, node: Node) -> None:
    """강한 커밋 — 정상 trust/stability로 저장."""
    existing = db_get_node(conn, node.address_hash)
    if existing is None:
        insert_node(conn, node)
    else:
        node.touch()
        update_node(conn, node)


def _commit_weak(conn: sqlite3.Connection, node: Node) -> None:
    """약한 커밋 — 매우 낮은 trust/stability로 저장."""
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
    이로써 반복 대화가 세계 그래프에 주는 충격을 완화한다.
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


# ── 수렴 판단 ─────────────────────────────────────────────────────────────────

def _has_converged(tg: TempThoughtGraph, prev_node_count: int, prev_edge_count: int) -> bool:
    """구조적 변화 감지 기반 수렴 판단."""
    delta = tg.current_delta()
    if delta.is_empty():
        return True

    current_node_count = len(tg.all_nodes())
    current_edge_count = len(tg.all_edges())
    if current_node_count == prev_node_count and current_edge_count == prev_edge_count:
        return True

    return False


# ── TranslatedEdge → TempThoughtGraph 변환 ───────────────────────────────────

def _add_translated_edges(
    tg: TempThoughtGraph,
    translated_edges: list[TranslatedEdge],
    added_keys: set[tuple[str, str]],
) -> None:
    """TranslatedEdge 목록에서 해결 가능한 항목을 TempThoughtGraph에 추가한다."""
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


class ThoughtEngine:
    """Think 루프 실행기."""

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
    ) -> ConclusionView:
        """Think 루프를 실행하고 ConclusionView를 반환한다."""
        _t0 = time.perf_counter()
        tg = TempThoughtGraph()

        tg.set_goal_node(self._goal_node)
        tg.load_from_translated(translated)

        if previous_key_hashes:
            for h in previous_key_hashes:
                if tg.get_node(h):
                    continue
                subgraph = extract_subgraph(self._conn, h)
                for n in subgraph.nodes:
                    if not tg.get_node(n.address_hash):
                        tg._nodes[n.address_hash] = n
                for e in subgraph.edges:
                    if e.edge_id not in tg._edges:
                        tg._edges[e.edge_id] = e
                        tg._adj.setdefault(e.source_hash, set()).add(e.target_hash)
                        tg._adj.setdefault(e.target_hash, set()).add(e.source_hash)

        _te_added_keys: set[tuple[str, str]] = set()
        _add_translated_edges(tg, translated.edges, _te_added_keys)

        from ..utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER
        for ref in translated.nodes:
            if isinstance(ref, ConceptPointer):
                tg.connect_to_goal(ref.address_hash)
                tg.connect_to_identity(ref.address_hash, ANCHOR_USER)

        identity_anchors = [ANCHOR_USER, ANCHOR_ASSISTANT]
        for anchor_h in identity_anchors:
            subgraph = extract_subgraph(self._conn, anchor_h)
            for n in subgraph.nodes:
                if not tg.get_node(n.address_hash):
                    tg._nodes[n.address_hash] = n
            for e in subgraph.edges:
                if e.edge_id not in tg._edges:
                    tg._edges[e.edge_id] = e
                    tg._adj.setdefault(e.source_hash, set()).add(e.target_hash)
                    tg._adj.setdefault(e.target_hash, set()).add(e.source_hash)

        _t0 = _t("graph init", _t0)

        had_empty_slots = tg.has_empty_slots()
        loop_count = 0
        prev_node_count = len(tg.all_nodes())
        prev_edge_count = len(tg.all_edges())
        search_node_hashes: set[str] = set()

        while loop_count < config.THINK_MAX_LOOPS:
            loop_count += 1
            tg.reset_delta()
            print(f"[think] loop {loop_count} start  nodes={len(tg.all_nodes())}  empty_slots={len(tg.empty_slots)}")

            if tg.has_empty_slots():
                _ts = time.perf_counter()
                existing_cp_hashes = {
                    ref.address_hash
                    for ref in translated.nodes
                    if isinstance(ref, ConceptPointer)
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

            if _has_converged(tg, prev_node_count, prev_edge_count):
                break

            prev_node_count = len(tg.all_nodes())
            prev_edge_count = len(tg.all_edges())

        concept_differentiation.run(tg)

        import math as _math

        scored: list[tuple[float, str]] = []
        for ref in translated.nodes:
            if isinstance(ref, ConceptPointer):
                h = ref.address_hash
            else:
                h = compute_hash(ref.concept_hint.strip())
            if tg.get_node(h) is None:
                continue
            scored.append((ref.importance, h))

        scored.sort(key=lambda x: x[0], reverse=True)
        n_sel = len(scored)
        n_near = max(1, _math.ceil(n_sel * config.TOKEN_IMPORTANCE_NEAR_RATIO))
        n_far = max(1, _math.ceil(n_sel * config.TOKEN_IMPORTANCE_FAR_RATIO))

        key_hashes: set[str] = {h for _, h in scored[:n_near]}
        far_cands: set[str] = {h for _, h in scored[max(0, n_sel - n_far):]}
        ref_hashes: set[str] = far_cands - key_hashes

        if previous_key_hashes:
            ref_hashes |= (previous_key_hashes - key_hashes)

        if not previous_key_hashes:
            topic_continuity = "new_topic"
        else:
            overlap = len(key_hashes.intersection(previous_key_hashes))
            if overlap >= 2:
                topic_continuity = "continued_topic"
            elif overlap == 1:
                topic_continuity = "related_topic"
            else:
                topic_continuity = "shifted_topic"

        _tc = time.perf_counter()
        tg.merge_duplicate_edges()
        self._commit_new_content(tg)
        _t("commit_new_content", _tc)

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
            search_node_hashes=search_node_hashes,
        )

    def _add_search_result_edges(self, tg: TempThoughtGraph, search_text: str) -> None:
        """검색 결과 텍스트에서 TempThoughtGraph에 이미 존재하는 노드 사이의 엣지를 추가한다."""
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
                if h in seen_hashes:
                    continue
                if tg.get_node(h) is None:
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

    async def _fill_empty_slots(
        self,
        tg: TempThoughtGraph,
        user_input: str | None = None,
        concept_hashes: set[str] | None = None,
    ) -> set[str]:
        """EmptySlot 전체를 1회 검색 → 각 슬롯을 ingest."""
        slots = list(tg.empty_slots)
        if not slots:
            return set()

        query = user_input or " ".join(slot.concept_hint for slot in slots)
        print(f"[think] search start  query_len={len(query)}  slots={len(slots)}")

        _ts = time.perf_counter()
        try:
            search_text = await asyncio.wait_for(self._search_fn(query), timeout=config.SEARCH_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"[think] search_fn timeout ({config.SEARCH_TIMEOUT}s) — 검색 결과 없이 계속")
            search_text = None
        _t(f"search_fn ({len(slots)} slots)", _ts)

        ingested_nodes: list[Node] = []
        session_search_hashes: set[str] = set()
        _ti = time.perf_counter()
        for slot in slots:
            node, got_search = await self._ingest_slot(slot, search_text=search_text)
            if node is not None:
                tg.fill_slot(slot, node)
                tg.connect_to_goal(node.address_hash)
                ingested_nodes.append(node)
                if got_search:
                    session_search_hashes.add(node.address_hash)
        _t(f"ingest_slots x{len(slots)}", _ti)

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
        """EmptySlot을 hint 기반 신규 노드로 등록한다."""
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

        try:
            embedding = await self._embed_fn(hint)
        except Exception:
            embedding = None

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
        """임시 사고 그래프의 결과를 WorldGraph에 반영한다."""
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
