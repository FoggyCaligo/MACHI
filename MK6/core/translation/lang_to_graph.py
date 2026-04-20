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


def _split_near_far(
    sentence_pairs: list[tuple[str, ConceptRef]],
    token_embs: dict[str, list[float]],
) -> tuple[list[tuple[str, ConceptRef]], list[tuple[str, ConceptRef]]]:
    """문장 내 토큰을 near(핵심)/far(참고) 두 그룹으로 분리한다.

    near: centroid에 가장 가까운 NEAR_RATIO 비율 → 핵심 키워드
          문장의 대표 개념. 중심 의미에 가장 가까운 토큰.
    far:  centroid에서 가장 먼 FAR_RATIO 비율 → 참고 개념
          도메인 특이 개념·고유명사 등 문장 내 독특한 토큰.

    - 선택 가능 풀(selectable): 2자 이상 토큰만 포함 (1자 조사·어미 제외).
    - near/far가 겹치는 경우 near 우선.
    - near는 최소 TOKEN_IMPORTANCE_MIN개 보장.
    - 두 그룹은 언어 구조에만 근거하며 그래프 상태와 무관하다.
    """
    if not sentence_pairs:
        return [], []

    n = len(sentence_pairs)
    tokens = [t for t, _ in sentence_pairs]
    refs   = [r for _, r in sentence_pairs]

    scores = _importance_scores(tokens, refs, token_embs)

    # 2자 이상 토큰만 선택 대상으로 한정 — 1자 조사·어미 제외
    selectable = [i for i in range(n) if len(tokens[i]) >= 2]
    if not selectable:
        selectable = list(range(n))

    sorted_desc = sorted(selectable, key=lambda i: scores[i], reverse=True)

    n_near = max(1, math.ceil(len(selectable) * config.TOKEN_IMPORTANCE_NEAR_RATIO))
    n_far  = max(1, math.ceil(len(selectable) * config.TOKEN_IMPORTANCE_FAR_RATIO))

    near_indices: set[int] = set(sorted_desc[:n_near])
    far_indices:  set[int] = set(sorted_desc[max(0, len(sorted_desc) - n_far):])
    far_indices -= near_indices   # near 우선: 겹치는 인덱스는 near에 귀속

    # near 최소 보장: selectable 내에서 점수 순으로 추가
    if len(near_indices) < config.TOKEN_IMPORTANCE_MIN:
        for idx in sorted_desc:
            near_indices.add(idx)
            far_indices.discard(idx)
            if len(near_indices) >= config.TOKEN_IMPORTANCE_MIN:
                break

    # 원래 순서(sentence 내 위치)를 유지한 채 반환
    near_pairs = [pair for i, pair in enumerate(sentence_pairs) if i in near_indices]
    far_pairs  = [pair for i, pair in enumerate(sentence_pairs) if i in far_indices]
    return near_pairs, far_pairs


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

    # 토큰별 최종 resolve → near/far 분리 → nodes/edges 추가
    all_near_refs: list[ConceptRef] = []
    all_far_refs:  list[ConceptRef] = []

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

        # 2. near(핵심)/far(참고) 분리 — 언어 구조 기반, 그래프 상태 무관
        near_pairs, far_pairs = _split_near_far(sentence_pairs, token_embs)

        # 3. near+far 합집합을 sentence 원래 순서로 재구성 → nodes/edges 추가
        selected_id_set = {id(p) for p in near_pairs} | {id(p) for p in far_pairs}
        selected_in_order = [p for p in sentence_pairs if id(p) in selected_id_set]
        selected_refs = [r for _, r in selected_in_order]

        for ref in selected_refs:
            nodes.append(ref)

        for i in range(len(selected_refs) - 1):
            edges.append(
                TranslatedEdge(
                    source_ref=selected_refs[i],
                    target_ref=selected_refs[i + 1],
                    edge_family="concept",
                    connect_type="neutral",
                    confidence=0.5,
                    proposed_connect_type=None,
                )
            )

        # 4. near/far 누적 (TranslatedGraph 필드용)
        all_near_refs.extend(r for _, r in near_pairs)
        all_far_refs.extend(r for _, r in far_pairs)

    return TranslatedGraph(
        nodes=nodes,
        edges=edges,
        source=text,
        near_refs=all_near_refs,
        far_refs=all_far_refs,
    )
