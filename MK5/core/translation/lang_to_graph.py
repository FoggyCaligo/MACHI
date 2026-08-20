"""LangToGraph — 언어를 그래프로 번역한다."""
from __future__ import annotations

import asyncio
import math
import sqlite3
from typing import Callable, Awaitable

from ..entities.node import Node
from ..entities.translated_graph import (
    ConceptPointer, EmptySlot, ConceptRef,
    TranslatedEdge, TranslatedGraph, LocalSubgraph, InputGraphBundle,
)
from ..storage.world_graph import get_node, get_words_for_surface
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


def _clone_pointer(ptr: ConceptPointer) -> ConceptPointer:
    """같은 후보 노드라도 토큰 위치마다 독립 importance를 가질 수 있게 복제한다."""
    return ConceptPointer(
        address_hash=ptr.address_hash,
        local_subgraph=ptr.local_subgraph,
        importance=ptr.importance,
        resolution_source=ptr.resolution_source,
    )


def _build_input_bundle(source: str, nodes: list[ConceptRef], edges: list[TranslatedEdge]) -> InputGraphBundle:
    """TranslatedGraph의 기존 산출물을 입력 국소그래프 묶음으로 명시화한다."""
    center_hashes: set[str] = set()
    direct_hashes: set[str] = set()
    context_hashes: set[str] = set()
    empty_hints: list[str] = []
    local_subgraphs: list[LocalSubgraph] = []
    seen_subgraphs: set[str] = set()

    for ref in nodes:
        if isinstance(ref, ConceptPointer):
            center_hashes.add(ref.address_hash)
            if ref.is_direct_input_match:
                direct_hashes.add(ref.address_hash)
            else:
                context_hashes.add(ref.address_hash)
            center = ref.local_subgraph.center_hash
            if center not in seen_subgraphs:
                seen_subgraphs.add(center)
                local_subgraphs.append(ref.local_subgraph)
        else:
            hint = ref.concept_hint.strip()
            if hint:
                empty_hints.append(hint)

    return InputGraphBundle(
        source=source,
        center_hashes=center_hashes,
        direct_hashes=direct_hashes,
        context_hashes=context_hashes,
        empty_hints=empty_hints,
        local_subgraphs=local_subgraphs,
        sentence_edges=list(edges),
    )


def _relation_from_existing_graph(
    ref_a: ConceptRef,
    ref_b: ConceptRef,
) -> tuple[str, str, float, str | None]:
    if not isinstance(ref_a, ConceptPointer) or not isinstance(ref_b, ConceptPointer):
        return "concept", "neutral", 0.5, None

    src = ref_a.address_hash
    tgt = ref_b.address_hash
    candidates = []
    for edge in ref_a.local_subgraph.edges + ref_b.local_subgraph.edges:
        endpoints = {edge.source_hash, edge.target_hash}
        if endpoints != {src, tgt}:
            continue
        if not edge.is_active:
            continue
        candidates.append(edge)

    if not candidates:
        return "concept", "neutral", 0.5, None

    priority = {"conflict": 4, "opposite": 3, "flow": 3, "neutral": 1}
    chosen = max(
        candidates,
        key=lambda edge: (
            priority.get(edge.connect_type, 0),
            edge.edge_weight * edge.trust_score,
            edge.support_count,
        ),
    )
    confidence = max(0.5, min(1.0, chosen.edge_weight * chosen.trust_score))
    return chosen.edge_family, chosen.connect_type, confidence, chosen.proposed_connect_type


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

    valid_embs = [e for e in embs if e is not None]
    if not valid_embs:
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
    """언어 입력 하나를 TranslatedGraph로 번역한다."""
    input_type: InputType = await classify(
        text,
        embed_fn,
        config.INPUT_CLASSIFIER_EMBED_THRESHOLD,
    )

    _subgraph_cache: dict[str, LocalSubgraph] = {}

    nodes: list[ConceptRef] = []
    edges: list[TranslatedEdge] = []

    if input_type != "natural":
        ref = EmptySlot(concept_hint=text)
        nodes.append(ref)
        bundle = _build_input_bundle(text, nodes, edges)
        return TranslatedGraph(nodes=nodes, edges=edges, source=text, input_bundle=bundle)

    sentences = tokenize(text)
    all_tokens: list[str] = [t for sent in sentences for t in sent]

    exact_pointers: dict[str, list[ConceptPointer]] = {}
    for token in all_tokens:
        normalized = normalize_text(token)
        if normalized in exact_pointers:
            continue

        pointer_candidates: list[ConceptPointer] = []
        for word_entry in get_words_for_surface(conn, normalized):
            node = get_node(conn, word_entry.address_hash)
            if node is None or not node.is_active:
                continue
            subgraph = extract_subgraph(conn, node.address_hash, cache=_subgraph_cache)
            pointer_candidates.append(
                ConceptPointer(
                    address_hash=node.address_hash,
                    local_subgraph=subgraph,
                    resolution_source="exact_match",
                )
            )

        if pointer_candidates:
            exact_pointers[normalized] = pointer_candidates

    candidate_nodes: list[Node] = []
    if exact_pointers:
        seen: set[str] = set()
        for ptrs in exact_pointers.values():
            for ptr in ptrs:
                for n in ptr.local_subgraph.nodes:
                    if n.address_hash not in seen and n.embedding is not None:
                        candidate_nodes.append(n)
                        seen.add(n.address_hash)

    token_embs: dict[str, list[float]] = {}
    if all_tokens:
        unique_tokens = list(dict.fromkeys(all_tokens))
        emb_results = await asyncio.gather(
            *[embed_fn(normalize_text(t)) for t in unique_tokens],
            return_exceptions=True,
        )
        token_embs = {
            tok: emb
            for tok, emb in zip(unique_tokens, emb_results)
            if isinstance(emb, list)
        }

    for sentence_tokens in sentences:
        sentence_groups: list[tuple[str, list[ConceptRef]]] = []
        for token in sentence_tokens:
            normalized = normalize_text(token)
            if normalized in exact_pointers:
                refs: list[ConceptRef] = [_clone_pointer(ptr) for ptr in exact_pointers[normalized]]
            elif candidate_nodes and token in token_embs:
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
                    refs = [
                        ConceptPointer(
                            address_hash=best_node.address_hash,
                            local_subgraph=subgraph,
                            resolution_source="semantic_local_candidate",
                        )
                    ]
                else:
                    refs = [EmptySlot(concept_hint=token)]
            else:
                refs = [EmptySlot(concept_hint=token)]
            sentence_groups.append((token, refs))

        sentence_pairs: list[tuple[str, ConceptRef]] = [
            (token, ref)
            for token, refs in sentence_groups
            for ref in refs
        ]

        _assign_importances(sentence_pairs, token_embs)

        for _, ref in sentence_pairs:
            nodes.append(ref)

        for i in range(len(sentence_groups) - 1):
            tok_a, refs_a = sentence_groups[i]
            tok_b, refs_b = sentence_groups[i + 1]
            if len(tok_a) >= 2 and len(tok_b) >= 2:
                for ref_a in refs_a:
                    for ref_b in refs_b:
                        edge_family, connect_type, confidence, proposed = _relation_from_existing_graph(ref_a, ref_b)
                        edges.append(
                            TranslatedEdge(
                                source_ref=ref_a,
                                target_ref=ref_b,
                                edge_family=edge_family,
                                connect_type=connect_type,
                                confidence=confidence,
                                proposed_connect_type=proposed,
                            )
                        )

    bundle = _build_input_bundle(text, nodes, edges)
    return TranslatedGraph(nodes=nodes, edges=edges, source=text, input_bundle=bundle)
