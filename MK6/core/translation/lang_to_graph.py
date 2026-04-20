"""LangToGraph — 언어를 그래프로 번역한다."""
from __future__ import annotations

import asyncio
import math
import sqlite3
from typing import Callable, Awaitable

from ..entities.node import Node
from ..entities.translated_graph import (
    ConceptPointer, EmptySlot, ConceptRef,
    TranslatedEdge, TranslatedGraph, LocalSubgraph,
)
from ..storage.world_graph import get_node, get_word
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


# ── 토큰 중요도 ───────────────────────────────────────────────────────────────

def _importance_scores(
    tokens: list[str],
    refs: list[ConceptRef],
    token_embs: dict[str, list[float]],
) -> list[float]:
    """문장 내 각 토큰의 중요도 점수를 계산한다.

    방법: 문장 centroid 임베딩과의 cosine 유사도.
    - ConceptPointer: local_subgraph의 center 노드 embedding 사용.
    - EmptySlot: token_embs에서 조회.
    - 임베딩 없는 토큰: 레이블 길이 기반 폴백 (0.5 + 0.3 × 정규화 길이).

    이 점수로 상위 TOKEN_IMPORTANCE_RATIO 비율 토큰만 노드로 남긴다.
    파티클("이", "가", "에")나 구두점(".")처럼 짧고 의미가 적은 토큰이
    자연스럽게 낮은 점수를 받아 걸러진다.
    """
    # 각 토큰의 임베딩 수집
    embs: list[list[float] | None] = []
    for token, ref in zip(tokens, refs):
        if isinstance(ref, ConceptPointer):
            center = next(
                (n for n in ref.local_subgraph.nodes
                 if n.address_hash == ref.address_hash),
                None,
            )
            embs.append(center.embedding if center is not None else None)
        else:
            embs.append(token_embs.get(token))

    # 사용 가능한 임베딩으로 centroid 계산
    valid_embs = [e for e in embs if e is not None]
    if not valid_embs:
        # 임베딩 전무 → 레이블 길이만으로 점수 산출
        max_len = max(len(t) for t in tokens) if tokens else 1
        return [len(t) / max_len for t in tokens]

    dim = len(valid_embs[0])
    n = len(valid_embs)
    centroid = [sum(e[i] for e in valid_embs) / n for i in range(dim)]

    scores: list[float] = []
    max_len = max(len(t) for t in tokens) if tokens else 1
    for token, emb in zip(tokens, embs):
        if emb is not None:
            scores.append(_cosine(emb, centroid))
        else:
            # cosine 점수 범위(보통 0.6~1.0)에 맞춰 길이 기반 점수를 보정
            scores.append(0.5 + 0.3 * (len(token) / max_len))
    return scores


def _filter_top_ratio(
    sentence_pairs: list[tuple[str, ConceptRef]],
    token_embs: dict[str, list[float]],
) -> list[tuple[str, ConceptRef]]:
    """문장 내 토큰을 중요도 상위 TOKEN_IMPORTANCE_RATIO 비율로 필터링한다.

    최소 TOKEN_IMPORTANCE_MIN개는 보장한다.
    """
    if not sentence_pairs:
        return []

    tokens = [t for t, _ in sentence_pairs]
    refs   = [r for _, r in sentence_pairs]

    scores = _importance_scores(tokens, refs, token_embs)

    n_keep = max(
        config.TOKEN_IMPORTANCE_MIN,
        math.ceil(len(sentence_pairs) * config.TOKEN_IMPORTANCE_RATIO),
    )
    n_keep = min(n_keep, len(sentence_pairs))

    # 점수 내림차순 인덱스, 원래 순서 보존을 위해 정렬 후 index set 구성
    top_indices = set(
        sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n_keep]
    )
    # 원래 순서(sentence 내 위치)를 유지한 채 반환
    return [pair for i, pair in enumerate(sentence_pairs) if i in top_indices]


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

    후보 풀 구성 원칙 (2패스):
      1패스: words 테이블 exact match → ConceptPointer 확보
      2패스: 1패스에서 얻은 LocalSubgraph 내 노드만 임베딩 유사도 후보로 사용
      후보가 없으면 바로 EmptySlot — Think 루프에서 검색으로 채운다.

    Args:
        text:     번역할 언어 입력
        conn:     World Graph DB 커넥션
        embed_fn: async 임베딩 함수 (str → list[float])

    Returns:
        TranslatedGraph — nodes(ConceptPointer | EmptySlot), edges(TranslatedEdge)
    """
    # ── 입력 타입 분류 ────────────────────────────────────────────────────────
    input_type: InputType = await classify(
        text,
        embed_fn,
        config.INPUT_CLASSIFIER_EMBED_THRESHOLD,
    )

    # 요청 단위 LocalSubgraph 캐시 — 같은 center_hash에 대한 BFS/DB 재조회 방지
    _subgraph_cache: dict[str, LocalSubgraph] = {}

    nodes: list[ConceptRef] = []
    edges: list[TranslatedEdge] = []

    if input_type != "natural":
        # 비자연어 — exact match 시도 후 없으면 EmptySlot
        ref = await _resolve_unit_as_embedding(text, conn, embed_fn, [])
        nodes.append(ref)
        return TranslatedGraph(nodes=nodes, edges=edges, source=text)

    # ── 자연어 경로 ───────────────────────────────────────────────────────────
    sentences = tokenize(text)
    all_tokens: list[str] = [t for sent in sentences for t in sent]

    # 1패스 — exact match만으로 ConceptPointer 수집
    exact_pointers: dict[str, ConceptPointer] = {}   # normalized → ConceptPointer
    for token in all_tokens:
        normalized = normalize_text(token)
        word_entry = get_word(conn, normalized)
        if word_entry is None:
            continue
        node = get_node(conn, word_entry.address_hash)
        if node is None or not node.is_active:
            continue
        subgraph = extract_subgraph(conn, node.address_hash, cache=_subgraph_cache)
        exact_pointers[normalized] = ConceptPointer(
            address_hash=node.address_hash,
            local_subgraph=subgraph,
        )

    # 2패스용 후보 풀 — 1패스 LocalSubgraph 합산
    candidate_nodes: list[Node] = []
    if exact_pointers:
        seen: set[str] = set()
        for ptr in exact_pointers.values():
            for n in ptr.local_subgraph.nodes:
                if n.address_hash not in seen and n.embedding is not None:
                    candidate_nodes.append(n)
                    seen.add(n.address_hash)

    # 2패스 — exact match 실패 토큰의 임베딩을 배치 처리
    # 후보 없으면 embed 호출 없이 바로 EmptySlot
    missed_tokens: list[str] = []
    for sent in sentences:
        for token in sent:
            if normalize_text(token) not in exact_pointers:
                missed_tokens.append(token)

    token_embs: dict[str, list[float]] = {}
    if candidate_nodes and missed_tokens:
        unique_missed = list(dict.fromkeys(missed_tokens))   # 중복 제거, 순서 유지
        emb_results = await asyncio.gather(
            *[embed_fn(normalize_text(t)) for t in unique_missed]
        )
        token_embs = dict(zip(unique_missed, emb_results))

    # 토큰별 최종 resolve → 중요도 필터링 → nodes/edges 추가
    for sentence_tokens in sentences:
        # 1. 각 토큰을 ConceptPointer 또는 EmptySlot으로 resolve
        sentence_pairs: list[tuple[str, ConceptRef]] = []
        for token in sentence_tokens:
            normalized = normalize_text(token)
            if normalized in exact_pointers:
                ref: ConceptRef = exact_pointers[normalized]
            elif token in token_embs:
                # 미리 계산된 임베딩으로 후보 비교
                tok_emb = token_embs[token]
                best_node: Node | None = None
                best_score = -1.0
                for node in candidate_nodes:
                    if node.embedding is None:
                        continue
                    score = _cosine(tok_emb, node.embedding)
                    if score > best_score:
                        best_score = score
                        best_node = node
                if best_node is not None and best_score >= config.LANG_TO_GRAPH_SIMILARITY_THRESHOLD:
                    subgraph = extract_subgraph(conn, best_node.address_hash, cache=_subgraph_cache)
                    ref = ConceptPointer(
                        address_hash=best_node.address_hash,
                        local_subgraph=subgraph,
                    )
                else:
                    ref = EmptySlot(concept_hint=token)
            else:
                # 후보 없음 → EmptySlot (embed 호출 없음)
                ref = EmptySlot(concept_hint=token)
            sentence_pairs.append((token, ref))

        # 2. 중요도 상위 TOKEN_IMPORTANCE_RATIO 필터링
        filtered_pairs = _filter_top_ratio(sentence_pairs, token_embs)

        # 3. 필터된 토큰만 nodes에 추가, 인접 쌍 → neutral 엣지
        filtered_refs = [r for _, r in filtered_pairs]
        for ref in filtered_refs:
            nodes.append(ref)

        for i in range(len(filtered_refs) - 1):
            edges.append(
                TranslatedEdge(
                    source_ref=filtered_refs[i],
                    target_ref=filtered_refs[i + 1],
                    edge_family="concept",
                    connect_type="neutral",
                    confidence=0.5,
                    proposed_connect_type=None,
                )
            )

    return TranslatedGraph(nodes=nodes, edges=edges, source=text)
