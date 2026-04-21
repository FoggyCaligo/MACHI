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

def _assign_importances(
    sentence_pairs: list[tuple[str, ConceptRef]],
    token_embs: dict[str, list[float]],
) -> None:
    """각 ConceptRef에 centroid 기반 중요도 점수를 in-place로 할당한다.

    방법: 문장 내 모든 토큰 임베딩의 centroid와 각 토큰의 cosine 유사도.
    - 모든 토큰: token_embs에서 실시간 임베딩 조회 (ConceptPointer의 WorldGraph
      저장 임베딩은 사용하지 않음 — 그래프 상태가 centroid를 오염시키지 않도록).
    - 임베딩 없는 토큰: 길이 기반 폴백 (0.5 + 0.3 × 정규화 길이).

    중요도 필터링(near/far 20%)은 ThoughtEngine에서 수행한다.
    LangToGraph는 모든 토큰을 넘기고 점수만 부여한다.
    """
    if not sentence_pairs:
        return

    tokens = [t for t, _ in sentence_pairs]
    embs: list[list[float] | None] = [token_embs.get(t) for t in tokens]

    # centroid 계산
    valid_embs = [e for e in embs if e is not None]
    if not valid_embs:
        # 임베딩 없음 → 길이만으로 점수
        max_len = max(len(t) for t in tokens) if tokens else 1
        for token, (_, ref) in zip(tokens, sentence_pairs):
            ref.importance = len(token) / max_len
        return

    dim = len(valid_embs[0])
    n = len(valid_embs)
    centroid = [sum(e[i] for e in valid_embs) / n for i in range(dim)]

    max_len = max(len(t) for t in tokens) if tokens else 1
    for token, emb, (_, ref) in zip(tokens, embs, sentence_pairs):
        if emb is not None:
            ref.importance = _cosine(emb, centroid)
        else:
            ref.importance = 0.5 + 0.3 * (len(token) / max_len)


# ── LangToGraph 메인 ──────────────────────────────────────────────────────────

async def translate(
    text: str,
    conn: sqlite3.Connection,
    embed_fn: EmbedFn,
) -> TranslatedGraph:
    """언어 입력 하나를 TranslatedGraph로 번역한다.

    저장은 하지 않는다. World Graph는 변경되지 않는다.

    반환되는 TranslatedGraph.nodes에는 문장의 모든 토큰이 포함된다.
    중요도 필터링(near/far 20%)은 ThoughtEngine에서 수행한다.
    각 ref의 importance 필드에 centroid 기반 중요도 점수가 담겨 있다.

    후보 풀 구성 원칙 (2패스):
      1패스: words 테이블 exact match → ConceptPointer 확보
      2패스: 1패스에서 얻은 LocalSubgraph 내 노드만 임베딩 유사도 후보로 사용
      후보가 없으면 바로 EmptySlot — Think 루프에서 검색으로 채운다.

    Args:
        text:     번역할 언어 입력
        conn:     World Graph DB 커넥션
        embed_fn: async 임베딩 함수 (str → list[float])

    Returns:
        TranslatedGraph — nodes(전체 ConceptRef), edges(TranslatedEdge)
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
        ref = EmptySlot(concept_hint=text)
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

    # 전체 토큰 임베딩 — 중요도 스코어링 및 2패스 resolution 공용
    # ConceptPointer 여부와 무관하게 모든 토큰을 실시간 embed한다.
    # → centroid가 그래프 상태(WorldGraph 저장 임베딩)에 오염되지 않음.
    token_embs: dict[str, list[float]] = {}
    if all_tokens:
        unique_tokens = list(dict.fromkeys(all_tokens))  # 중복 제거, 순서 유지
        # return_exceptions=True: 일부 임베딩 실패(ReadTimeout 등)가 있어도
        # 나머지는 정상 처리. 실패한 토큰은 token_embs에서 누락 → 길이 기반 폴백.
        emb_results = await asyncio.gather(
            *[embed_fn(normalize_text(t)) for t in unique_tokens],
            return_exceptions=True,
        )
        token_embs = {
            tok: emb
            for tok, emb in zip(unique_tokens, emb_results)
            if isinstance(emb, list)
        }

    # 토큰별 resolve → 중요도 할당 → nodes/edges 추가
    for sentence_tokens in sentences:
        # 1. 각 토큰을 ConceptPointer 또는 EmptySlot으로 resolve
        sentence_pairs: list[tuple[str, ConceptRef]] = []
        for token in sentence_tokens:
            normalized = normalize_text(token)
            if normalized in exact_pointers:
                ref: ConceptRef = exact_pointers[normalized]
            elif candidate_nodes and token in token_embs:
                # 2패스: 미리 계산된 임베딩으로 후보 비교
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
                # 후보 없음 → EmptySlot
                ref = EmptySlot(concept_hint=token)
            sentence_pairs.append((token, ref))

        # 2. 모든 토큰에 중요도 점수 할당 (in-place)
        _assign_importances(sentence_pairs, token_embs)

        # 3. 모든 토큰을 nodes에 추가 (필터링 없음)
        #    중요도 필터링(near/far 20%)은 ThoughtEngine에서 수행한다.
        for _, ref in sentence_pairs:
            nodes.append(ref)

        # 4. 인접 토큰 쌍 → TranslatedEdge (양쪽 모두 2자 이상 토큰인 경우만)
        #    엣지는 의미 단위 간 관계 후보. connect_type은 ThoughtEngine이 확정.
        for i in range(len(sentence_pairs) - 1):
            tok_a, ref_a = sentence_pairs[i]
            tok_b, ref_b = sentence_pairs[i + 1]
            if len(tok_a) >= 2 and len(tok_b) >= 2:
                edges.append(
                    TranslatedEdge(
                        source_ref=ref_a,
                        target_ref=ref_b,
                        edge_family="concept",
                        connect_type="neutral",
                        confidence=0.5,
                        proposed_connect_type=None,
                    )
                )

    return TranslatedGraph(nodes=nodes, edges=edges, source=text)
