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

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Awaitable

from ..entities.node import Node
from ..entities.edge import Edge
from ..entities.word_entry import WordEntry
from ..entities.translated_graph import TranslatedGraph, ConceptPointer, EmptySlot
from ..storage.world_graph import (
    insert_node, update_node, insert_edge, update_edge,
    get_node as db_get_node, get_edge as db_get_edge,
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
    known_hashes: set[str] = field(default_factory=set)
    # known_hashes: think() 시작 시 이미 DB에 존재했던 ConceptPointer 노드의 hash 집합.
    # GraphToLang에서 "핵심 키워드"(기존 개념) vs "참고 개념"(신규 ingest) 분류에 사용한다.


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
    if db_get_edge(conn, edge.edge_id) is None:
        insert_edge(conn, edge)
    else:
        update_edge(conn, edge)


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
        tg = TempThoughtGraph()

        # ── 임시 사고 그래프 구성 ─────────────────────────────────────────────
        tg.set_goal_node(self._goal_node)
        tg.load_from_translated(translated)

        # ConceptPointer들을 목표 노드에 임시 연결 + known_hashes 수집
        # known_hashes: think() 시작 시점에 이미 DB에 존재하던 개념들.
        # GraphToLang에서 "핵심 키워드" 분류의 기준이 된다.
        known_hashes: set[str] = set()
        for ref in translated.nodes:
            if isinstance(ref, ConceptPointer):
                tg.connect_to_goal(ref.address_hash)
                known_hashes.add(ref.address_hash)

        had_empty_slots = tg.has_empty_slots()
        loop_count = 0
        prev_node_count = len(tg.all_nodes())
        prev_edge_count = len(tg.all_edges())

        # ── Think 루프 ────────────────────────────────────────────────────────
        while loop_count < config.THINK_MAX_LOOPS:
            loop_count += 1
            tg.reset_delta()

            # 1. EmptySlot 처리 — 필요 시 검색
            if tg.has_empty_slots():
                await self._fill_empty_slots(
                    tg, user_input=user_input, known_hashes=known_hashes
                )

            # 2. ConceptDifferentiation
            diff_results = concept_differentiation.run(tg)

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

        # ── 세계그래프 강한 커밋 (새로 추가된 노드/엣지) ─────────────────────
        self._commit_new_content(tg)

        return ConclusionView(
            nodes=tg.all_nodes(),
            edges=tg.all_edges(),
            goal_hash=tg.goal_hash,
            had_empty_slots=had_empty_slots,
            loop_count=loop_count,
            model=model,
            user_input=user_input,
            known_hashes=known_hashes,
        )

    async def _fill_empty_slots(
        self,
        tg: TempThoughtGraph,
        user_input: str | None = None,
        known_hashes: set[str] | None = None,
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
        search_text = await self._search_fn(query)

        # 각 슬롯을 ingest — 검색 결과를 payload에 함께 저장
        ingested_nodes: list[Node] = []
        for slot in slots:
            node = await self._ingest_slot(slot, search_text=search_text)
            if node is not None:
                tg.fill_slot(slot, node)
                tg.connect_to_goal(node.address_hash)
                ingested_nodes.append(node)

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
            if known_hashes:
                for ingest_node in ingested_nodes:
                    for cp_hash in known_hashes:
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

        - is_abstract 노드: 약한 커밋
        - is_temporary 엣지: 건너뜀 (목표 연결 엣지 등)
        - 나머지 신규 노드/엣지: 강한 커밋
        """
        delta = tg.current_delta()

        for address_hash in delta.added_nodes:
            node = tg.get_node(address_hash)
            if node is None:
                continue
            if node.is_abstract:
                _commit_weak(self._conn, node)
            else:
                _commit_strong(self._conn, node)

        for edge_id in delta.added_edges:
            edge = tg.get_edge(edge_id)   # O(1) dict 조회
            if edge is None:
                continue
            if edge.is_temporary:
                continue
            _commit_edge(self._conn, edge, strong=True)

        self._conn.commit()
