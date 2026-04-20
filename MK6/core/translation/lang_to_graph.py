"""LangToGraph — 언어를 그래프로 번역한다."""
from __future__ import annotations

import math
import sqlite3
from typing import Callable, Awaitable

from ..entities.node import Node
from ..entities.translated_graph import (
    ConceptPointer, EmptySlot, ConceptRef,
    TranslatedEdge, TranslatedGraph,
)
from ..storage.world_graph import get_node, get_word, get_active_nodes
from ..utils.hash_resolver import normalize_text
from ..utils.local_graph_extractor import extract as extract_subgraph
from .input_classifier import classify, InputType
from .token_splitter import tokenize
from ... import config


EmbedFn = Callable[[str], Awaitable[list[float]]]


# ── 유사도 ────────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── 개념 단위 조회 ────────────────────────────────────────────────────────────

async def _resolve_token(
    token: str,
    conn: sqlite3.Connection,
    embed_fn: EmbedFn,
    candidate_nodes: list[Node],
) -> ConceptRef:
    """토큰 하나를 ConceptPointer 또는 EmptySlot으로 변환한다.

    1단계: words 테이블 exact match
    2단계: 임베딩 유사도 (active nodes 후보 풀)
    """
    normalized = normalize_text(token)

    # 1단계 — exact match
    word_entry = get_word(conn, normalized)
    if word_entry is not None:
        node = get_node(conn, word_entry.address_hash)
        if node is not None and node.is_active:
            subgraph = extract_subgraph(conn, node.address_hash)
            return ConceptPointer(
                address_hash=node.address_hash,
                local_subgraph=subgraph,
            )

    # 2단계 — 임베딩 유사도
    if not candidate_nodes:
        return EmptySlot(concept_hint=token)

    token_emb = await embed_fn(normalized)

    best_node: Node | None = None
    best_score = -1.0
    for node in candidate_nodes:
        if node.embedding is None:
            continue
        score = _cosine(token_emb, node.embedding)
        if score > best_score:
            best_score = score
            best_node = node

    if best_node is not None and best_score >= config.LANG_TO_GRAPH_SIMILARITY_THRESHOLD:
        subgraph = extract_subgraph(conn, best_node.address_hash)
        return ConceptPointer(
            address_hash=best_node.address_hash,
            local_subgraph=subgraph,
        )

    return EmptySlot(concept_hint=token)


async def _resolve_unit_as_embedding(
    text: str,
    conn: sqlite3.Connection,
    embed_fn: EmbedFn,
    candidate_nodes: list[Node],
) -> ConceptRef:
    """비자연어 입력(code/path/url)을 단일 단위로 처리한다."""
    if not candidate_nodes:
        return EmptySlot(concept_hint=text)

    unit_emb = await embed_fn(text)

    best_node: Node | None = None
    best_score = -1.0
    for node in candidate_nodes:
        if node.embedding is None:
            continue
        score = _cosine(unit_emb, node.embedding)
        if score > best_score:
            best_score = score
            best_node = node

    if best_node is not None and best_score >= config.LANG_TO_GRAPH_SIMILARITY_THRESHOLD:
        subgraph = extract_subgraph(conn, best_node.address_hash)
        return ConceptPointer(
            address_hash=best_node.address_hash,
            local_subgraph=subgraph,
        )

    return EmptySlot(concept_hint=text)


# ── LangToGraph 메인 ──────────────────────────────────────────────────────────

async def translate(
    text: str,
    conn: sqlite3.Connection,
    embed_fn: EmbedFn,
) -> TranslatedGraph:
    """언어 입력 하나를 TranslatedGraph로 번역한다.

    저장은 하지 않는다. World Graph는 변경되지 않는다.

    Args:
        text:     번역할 언어 입력
        conn:     World Graph DB 커넥션
        embed_fn: async 임베딩 함수 (str → list[float])

    Returns:
        TranslatedGraph — nodes(ConceptPointer | EmptySlot), edges(TranslatedEdge)
    """
    # 임베딩 후보 풀 — 매 호출마다 최대 N개 활성 노드를 로드
    # (임베딩이 있는 노드 우선, trust_score 내림차순)
    all_active = get_active_nodes(conn)
    candidate_nodes = sorted(
        (n for n in all_active if n.embedding is not None),
        key=lambda n: n.trust_score,
        reverse=True,
    )[: config.LANG_TO_GRAPH_MAX_EMBEDDING_NODES]

    # ── 입력 타입 분류 ────────────────────────────────────────────────────────
    input_type: InputType = await classify(
        text,
        embed_fn,
        config.INPUT_CLASSIFIER_EMBED_THRESHOLD,
    )

    nodes: list[ConceptRef] = []
    edges: list[TranslatedEdge] = []

    if input_type != "natural":
        # 비자연어 — 전체를 단일 단위로 처리
        ref = await _resolve_unit_as_embedding(text, conn, embed_fn, candidate_nodes)
        nodes.append(ref)
        return TranslatedGraph(nodes=nodes, edges=edges, source=text)

    # ── 자연어 경로 ───────────────────────────────────────────────────────────
    sentences = tokenize(text)  # list[list[str]]

    for sentence_tokens in sentences:
        sentence_refs: list[ConceptRef] = []

        for token in sentence_tokens:
            ref = await _resolve_token(token, conn, embed_fn, candidate_nodes)
            nodes.append(ref)
            sentence_refs.append(ref)

        # 동일 문장 내 인접 토큰 쌍 → neutral 엣지
        # 관계 타입 확정은 ThoughtEngine이 담당
        for i in range(len(sentence_refs) - 1):
            src = sentence_refs[i]
            tgt = sentence_refs[i + 1]
            edges.append(
                TranslatedEdge(
                    source_ref=src,
                    target_ref=tgt,
                    edge_family="concept",
                    connect_type="neutral",
                    confidence=0.5,
                    proposed_connect_type=None,
                )
            )

    return TranslatedGraph(nodes=nodes, edges=edges, source=text)
