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
from typing import Callable, Awaitable


def _t(label: str, start: float) -> float:
    """경과 시간을 출력하고 현재 시각을 반환한다."""
    elapsed = time.perf_counter() - start
    print(f"[think] {label}: {elapsed:.3f}s")
    return time.perf_counter()

from ..entities.node import Node
from ..entities.edge import Edge
from ..entities.word_entry import WordEntry
from ..entities.translated_graph import TranslatedGraph, TranslatedEdge, ConceptPointer, EmptySlot
from ..storage.world_graph import (
    insert_node, update_node, insert_edge, update_edge,
    get_node as db_get_node, get_edge as db_get_edge,
    get_edge_by_endpoints as db_get_edge_by_endpoints,
    insert_word, get_word,
    remap_words_to_node,
)
from ..utils.hash_resolver import compute_hash, normalize_text
from .temp_thought_graph import TempThoughtGraph
from . import concept_differentiation
from ... import config


EmbedFn = Callable[[str], Awaitable[list[float]]]


# ── ConclusionView ────────────────────────────────────────────────────────────

@dataclass
class ConclusionView:
    """Think 루프 종료 후 GraphToLang에 전달되는 최종 구조."""
    nodes: list[Node]
    edges: list[Edge]
    goal_hash: str | None
    had_empty_slots: bool
    loop_count: int
    model: str | None = None                    # 이번 요청에서 사용할 생성 모델
    user_input: str | None = None               # 원래 사용자 입력 (GraphToLang 컨텍스트용)
    key_hashes: set[str] = field(default_factory=set)
    # key_hashes: near 그룹 (centroid 가까운 토큰) — GraphToLang 핵심 키워드 분류 기준.
    ref_hashes: set[str] = field(default_factory=set)
    # ref_hashes: far 그룹 (centroid 먼 토큰) — GraphToLang 참고 개념 분류 기준.
    # 두 필드 모두 언어 구조 기반이며 그래프 상태(DB 존재 여부)와 무관하다.


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


def _commit_edge(conn: sqlite3.Connection, edge: Edge, strong: bool) -> None:
    if not strong:
        edge.trust_score = min(edge.trust_score, config.COMMIT_TRUST_WEAK)
        edge.edge_weight = min(edge.edge_weight, 0.2)
    edge.is_temporary = False
    edge.touch()

    # 같은 edge_id가 이미 DB에 있으면 단순 update
    if db_get_edge(conn, edge.edge_id) is not None:
        update_edge(conn, edge)
        return

    if strong:
        # 같은 endpoints의 기존 엣지가 있으면 강화 (weight 누적, support_count 증가)
        # edge_id는 매번 새 UUID이므로 endpoints 기준으로 동일 관계를 식별한다.
        existing = db_get_edge_by_endpoints(conn, edge.source_hash, edge.target_hash)
        if existing is not None:
            existing.edge_weight += edge.edge_weight
            existing.support_count += 1
            existing.touch()
            update_edge(conn, existing)
            return

    insert_edge(conn, edge)


# ── 수렴 판단 ─────────────────────────────────────────────────────────────────

def _has_converged(tg: TempThoughtGraph, prev_node_count: int, prev_edge_count: int) -> bool:
    """구조적 변화 감지 기반 수렴 판단.

    - 이번 회차에서 노드/엣지 변경이 없으면 수렴
    - 노드 수, 엣지 수가 이전 회차와 동일해도 수렴 (안전 보완)
    """
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
    """TranslatedEdge 목록에서 해결 가능한 항목을 TempThoughtGraph에 추가한다.

    - ConceptPointer 엔드포인트: address_hash로 즉시 해결.
    - EmptySlot 엔드포인트: compute_hash(hint)로 노드 존재 여부 확인.
      노드가 없으면 건너뜀 (fill 이후 재호출 시 처리).
    - added_keys: (src_hash, tgt_hash) 쌍으로 중복 추가 방지.
    - edge_weight = TranslatedEdge.confidence (0.5) — co_occurrence(0.5~0.6)와 동급,
      세션이 쌓이며 WorldGraph에서 반복 강화되면 자연히 올라간다.
    """
    now = datetime.now(timezone.utc)
    for te in translated_edges:
        # source 해결
        if isinstance(te.source_ref, ConceptPointer):
            src_hash = te.source_ref.address_hash
        else:
            src_hash = compute_hash(te.source_ref.concept_hint.strip())
            if tg.get_node(src_hash) is None:
                continue  # 아직 fill 안 됨

        # target 해결
        if isinstance(te.target_ref, ConceptPointer):
            tgt_hash = te.target_ref.address_hash
        else:
            tgt_hash = compute_hash(te.target_ref.concept_hint.strip())
            if tg.get_node(tgt_hash) is None:
                continue  # 아직 fill 안 됨

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


# ── ThoughtEngine ─────────────────────────────────────────────────────────────

class ThoughtEngine:
    """Think 루프 실행기.

    Args:
        conn:      WorldGraph DB 커넥션
        embed_fn:  async 임베딩 함수
        search_fn: async 검색 함수 (query: str) → str | None
                   결과 없으면 None 반환
        goal_node: 목표 노드 (WorldGraph에서 로드된 고정 앵커)
    """

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
    ) -> ConclusionView:
        """Think 루프를 실행하고 ConclusionView를 반환한다.

        Args:
            translated: LangToGraph가 반환한 사용자 입력 번역 결과
            model:      GraphToLang에서 사용할 생성 모델 (None이면 config 기본값)

        Returns:
            ConclusionView — GraphToLang에 넘길 최종 그래프 구조
        """
        _t0 = time.perf_counter()
        tg = TempThoughtGraph()

        # ── 임시 사고 그래프 구성 ─────────────────────────────────────────────
        tg.set_goal_node(self._goal_node)
        tg.load_from_translated(translated)

        # TranslatedEdge → TempThoughtGraph 변환 (CP↔CP는 즉시, EmptySlot 포함은 fill 후)
        _te_added_keys: set[tuple[str, str]] = set()
        _add_translated_edges(tg, translated.edges, _te_added_keys)

        # ConceptPointer들을 목표 노드에 임시 연결
        # key_hashes / ref_hashes: near/far 그룹 기반 분류 (언어 구조 기반, 그래프 상태 무관).
        # GraphToLang에서 "핵심 키워드" / "참고 개념" 분류의 기준이 된다.
        key_hashes: set[str] = set()   # near 그룹 → 핵심 키워드
        ref_hashes: set[str] = set()   # far 그룹  → 참고 개념
        for ref in translated.near_refs:
            if isinstance(ref, ConceptPointer):
                tg.connect_to_goal(ref.address_hash)
                key_hashes.add(ref.address_hash)
        for ref in translated.far_refs:
            if isinstance(ref, ConceptPointer):
                tg.connect_to_goal(ref.address_hash)
                ref_hashes.add(ref.address_hash)

        _t0 = _t("graph init", _t0)

        had_empty_slots = tg.has_empty_slots()
        loop_count = 0
        prev_node_count = len(tg.all_nodes())
        prev_edge_count = len(tg.all_edges())

        # ── Think 루프 ────────────────────────────────────────────────────────
        while loop_count < config.THINK_MAX_LOOPS:
            loop_count += 1
            tg.reset_delta()
            print(f"[think] loop {loop_count} start  nodes={len(tg.all_nodes())}  empty_slots={len(tg.empty_slots)}")

            # 1. EmptySlot 처리 — 필요 시 검색
            if tg.has_empty_slots():
                _ts = time.perf_counter()
                await self._fill_empty_slots(
                    tg, user_input=user_input, concept_hashes=key_hashes | ref_hashes
                )
                _t0 = _t(f"fill_empty_slots (loop {loop_count})", _ts)
                # fill 완료 후 EmptySlot 엔드포인트 포함 TranslatedEdge 추가
                _add_translated_edges(tg, translated.edges, _te_added_keys)

            # 2. ConceptDifferentiation
            _td = time.perf_counter()
            diff_results = concept_differentiation.run(tg)
            _t(f"concept_diff (loop {loop_count})", _td)

            # 3. 유의미한 분화가 발생했으면 약한 커밋 (즉시)
            for result in diff_results:
                _commit_weak(self._conn, result.abstract_node)
                for edge in result.edges_added:
                    _commit_edge(self._conn, edge, strong=False)

            # 4. 수렴 판단
            if _has_converged(tg, prev_node_count, prev_edge_count):
                break

            prev_node_count = len(tg.all_nodes())
            prev_edge_count = len(tg.all_edges())

        # ── 루프 종료 후 ConceptDifferentiation (최종 1회) ───────────────────
        concept_differentiation.run(tg)

        # ── EmptySlot → 해시 분류 (near/far 그룹 기반) ───────────────────────
        # _fill_empty_slots에서 채워진 노드는 compute_hash(hint)로 address_hash가
        # 결정된다. 루프 종료 후 tg에 노드가 존재하면 해당 그룹에 귀속한다.
        for ref in translated.near_refs:
            if isinstance(ref, EmptySlot):
                h = compute_hash(ref.concept_hint.strip())
                if tg.get_node(h) is not None:
                    key_hashes.add(h)
        for ref in translated.far_refs:
            if isinstance(ref, EmptySlot):
                h = compute_hash(ref.concept_hint.strip())
                if tg.get_node(h) is not None:
                    ref_hashes.add(h)

        # ── 세계그래프 강한 커밋 (새로 추가된 노드/엣지) ─────────────────────
        _tc = time.perf_counter()
        self._commit_new_content(tg)
        _t("commit_new_content", _tc)

        return ConclusionView(
            nodes=tg.all_nodes(),
            edges=tg.all_edges(),
            goal_hash=tg.goal_hash,
            had_empty_slots=had_empty_slots,
            loop_count=loop_count,
            model=model,
            user_input=user_input,
            key_hashes=key_hashes,
            ref_hashes=ref_hashes,
        )

    def _add_search_result_edges(
        self,
        tg: TempThoughtGraph,
        search_text: str,
    ) -> None:
        """검색 결과 텍스트에서 TempThoughtGraph에 이미 존재하는 노드 사이의 엣지를 추가한다.

        LLM/임베딩을 사용하지 않는다. DB exact match (words 테이블)만 사용한다.

        처리 순서:
        1. extract_tokens으로 토크나이징 (구두점·조사 제거)
        2. 각 토큰을 normalize → words 테이블 exact match → address_hash 획득
        3. 해당 hash가 TempThoughtGraph에 존재하면 "언급된 기존 노드" 목록에 추가
        4. 목록 내 모든 쌍에 co_occurrence 엣지 생성 (이미 연결된 쌍 제외)
        """
        from ..translation.token_splitter import extract_tokens
        from ..utils.hash_resolver import normalize_text

        tokens = extract_tokens(search_text)
        if not tokens:
            return

        # exact match로 TempThoughtGraph에 존재하는 노드만 수집 (순서 유지, 중복 제거)
        mentioned: list[str] = []   # address_hash 목록
        seen_hashes: set[str] = set()
        for token in tokens:
            normalized = normalize_text(token)
            word_entry = get_word(self._conn, normalized)
            if word_entry is None:
                continue
            h = word_entry.address_hash
            if h in seen_hashes:
                continue
            if tg.get_node(h) is None:
                continue
            seen_hashes.add(h)
            mentioned.append(h)

        if len(mentioned) < 2:
            return

        # 존재하는 노드 쌍에 엣지 추가 (중복 방지)
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
    ) -> None:
        """EmptySlot 전체를 1회 검색 → 각 슬롯을 ingest.

        설계:
        - 슬롯마다 개별 검색하지 않는다. user_input 원문(있으면)을 검색 쿼리로 쓴다.
          user_input이 없으면 hint 합산 쿼리를 사용한다.
          원문 쿼리가 개별 토큰 합산보다 의미 있는 검색 결과를 돌려준다.
        - 검색 결과는 lang_to_graph로 파싱하지 않는다.
          (빈 DB에서 파싱하면 EmptySlot cascade + PoolTimeout 발생)
        - _ingest_slot으로 hint마다 노드를 직접 생성하고,
          검색 결과를 payload["search_summary"]에 저장한다.
        - GraphToLang이 payload를 LLM 컨텍스트로 활용한다.
        """
        slots = list(tg.empty_slots)
        if not slots:
            return

        # user_input이 있으면 원문을 쿼리로, 없으면 hint 합산
        query = user_input or " ".join(slot.concept_hint for slot in slots)
        print(f"[think] search start  query_len={len(query)}  slots={len(slots)}")

        _ts = time.perf_counter()
        try:
            search_text = await asyncio.wait_for(
                self._search_fn(query),
                timeout=config.SEARCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print(f"[think] search_fn timeout ({config.SEARCH_TIMEOUT}s) — 검색 결과 없이 계속")
            search_text = None
        _t(f"search_fn ({len(slots)} slots)", _ts)

        # 각 슬롯을 ingest — 검색 결과를 payload에 함께 저장
        ingested_nodes: list[Node] = []
        _ti = time.perf_counter()
        for slot in slots:
            node = await self._ingest_slot(slot, search_text=search_text)
            if node is not None:
                tg.fill_slot(slot, node)
                tg.connect_to_goal(node.address_hash)
                ingested_nodes.append(node)
        _t(f"ingest_slots x{len(slots)}", _ti)

        # 검색 컨텍스트에서 함께 등장한 노드들 간 co_occurrence 엣지 생성.
        # 새 노드는 만들지 않고, 같은 쿼리에서 함께 등장한 개념들만 연결한다:
        #   ① ingest ↔ ingest  (검색 키워드 간)
        #   ② ingest ↔ ConceptPointer  (신규 개념 ↔ 기존 개념)
        # LangToGraph의 토큰 중요도 필터(상위 20%)가 이미 업스트림에서
        # 비중요 토큰을 제거하므로 여기서는 별도 상한을 두지 않는다.
        if ingested_nodes:
            now = datetime.now(timezone.utc)

            # ① ingest ↔ ingest (순수 근접 관계 — weight 0.5)
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

            # ② ingest ↔ ConceptPointer (의미 연관 — weight 0.6)
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

        # 검색 결과 텍스트로부터 기존 노드 간 엣지 추가.
        # TempThoughtGraph에 이미 존재하는 ConceptPointer 쌍에 대해서만 엣지를 생성한다.
        # EmptySlot 엔드포인트는 건너뜀 — 새 노드를 만들지 않는다.
        if search_text:
            self._add_search_result_edges(tg, search_text)

    async def _ingest_slot(
        self,
        slot: EmptySlot,
        search_text: str | None = None,
    ) -> Node | None:
        """EmptySlot을 hint 기반 신규 노드로 등록한다.

        처리:
        1. hint 정규화 → address_hash 계산
        2. 이미 WorldGraph에 있으면 재사용
           (search_text가 새로 주어지고 기존 노드에 요약이 없으면 payload 보강)
        3. 없으면 임베딩 계산 → 신규 Node 생성 → 약한 커밋
        4. words 테이블에도 등록 (없는 경우에만)

        Args:
            slot:        처리할 EmptySlot
            search_text: 검색 결과 원문. 있으면 payload["search_summary"]에 저장한다.
                         GraphToLang이 이를 LLM 컨텍스트로 활용한다.

        Returns:
            생성 또는 기존 Node. 임베딩 실패 시 None.
        """
        _SUMMARY_MAX = 800   # payload에 저장할 검색 요약 최대 길이

        hint = slot.concept_hint.strip()
        if not hint:
            return None

        address_hash = compute_hash(hint)

        # 이미 존재하면 재사용 (search_text로 payload 보강)
        existing = db_get_node(self._conn, address_hash)
        if existing is not None:
            if search_text and not existing.payload.get("search_summary"):
                existing.payload["search_summary"] = search_text[:_SUMMARY_MAX]
                existing.touch()
                update_node(self._conn, existing)
                self._conn.commit()
            return existing

        # 임베딩 계산
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

        # WorldGraph 약한 커밋
        insert_node(self._conn, node)

        # words 테이블 등록
        normalized = normalize_text(hint)
        if get_word(self._conn, normalized) is None:
            insert_word(self._conn, WordEntry(
                word_id=str(uuid.uuid4()),
                surface_form=normalized,
                address_hash=address_hash,
                language=None,
                created_at=now,
            ))

        self._conn.commit()
        return node

    def _commit_new_content(self, tg: TempThoughtGraph) -> None:
        """임시 사고 그래프의 결과를 WorldGraph에 반영한다.

        루프 전체 누적 추가 목록(all_added_*)을 사용한다.
        reset_delta()로 초기화되는 current_delta()를 쓰면 다회 루프 시
        이전 회차에서 추가된 노드/엣지가 커밋에서 누락되는 버그가 발생한다.

        - is_abstract 노드: 약한 커밋
        - is_temporary 엣지: 건너뜀 (목표 연결 엣지 등)
        - 나머지 신규 노드/엣지: 강한 커밋
        """
        for address_hash in tg.all_added_node_hashes:
            node = tg.get_node(address_hash)
            if node is None:
                continue
            if node.is_abstract:
                _commit_weak(self._conn, node)
            else:
                _commit_strong(self._conn, node)

        for edge_id in tg.all_added_edge_ids:
            edge = tg.get_edge(edge_id)   # O(1) dict 조회
            if edge is None:
                continue
            if edge.is_temporary:
                continue
            _commit_edge(self._conn, edge, strong=True)

        self._conn.commit()
