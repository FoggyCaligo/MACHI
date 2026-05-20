"""ConceptMerge — 충분히 안정적인 근거가 있는 노드만 보수적으로 통합."""
from __future__ import annotations

from itertools import combinations

from ... import config
from .concept_differentiation import composite_score
from .temp_thought_graph import TempThoughtGraph


# 병합은 irreversible에 가까우므로 분화보다 훨씬 보수적이어야 한다.
MERGE_THRESHOLD = 0.985
MIN_STABILITY_FOR_MERGE = 0.65
MIN_SHARED_NEIGHBORS_FOR_MERGE = 2
MIN_SUPPORT_FOR_MERGE = 2


def run(tg: TempThoughtGraph) -> int:
    """임시 사고 그래프 내 노드 쌍을 검사해 병합을 수행한다.

    Returns:
        병합된 노드 쌍의 수
    """
    merge_count = 0

    nodes = [
        n for n in tg.all_nodes()
        if n.embedding is not None
        and n.is_active
        and not n.is_abstract
        and n.address_hash != tg.goal_hash
    ]

    neighbor_cache = {
        n.address_hash: tg.neighbor_hashes(n.address_hash)
        for n in nodes
    }

    delta = tg.current_delta()
    modified_hashes = set(delta.added_nodes) | set(delta.modified_nodes)
    new_hashes = set(delta.added_nodes)

    for node_a, node_b in combinations(nodes, 2):
        hash_a, hash_b = node_a.address_hash, node_b.address_hash

        if tg.get_node(hash_a) is None or tg.get_node(hash_b) is None:
            continue

        if hash_a not in modified_hashes and hash_b not in modified_hashes:
            if tg.is_pair_checked(hash_a, hash_b):
                continue

        tg.mark_pair_checked(hash_a, hash_b)

        neighbors_a = neighbor_cache[hash_a]
        neighbors_b = neighbor_cache[hash_b]
        if not _is_merge_allowed(tg, node_a, node_b, neighbors_a, neighbors_b, new_hashes):
            continue

        score = composite_score(node_a, node_b, neighbors_a, neighbors_b)
        if score >= MERGE_THRESHOLD:
            if node_a.stability_score >= node_b.stability_score:
                survivor, deprecated = node_a, node_b
            else:
                survivor, deprecated = node_b, node_a

            print(
                f"[merge] merging {deprecated.primary_label() or deprecated.address_hash[:8]} "
                f"into {survivor.primary_label() or survivor.address_hash[:8]} (score={score:.3f})"
            )
            tg.merge_nodes(deprecated.address_hash, survivor.address_hash)
            merge_count += 1

    return merge_count


def _is_merge_allowed(tg, node_a, node_b, neighbors_a: set[str], neighbors_b: set[str], new_hashes: set[str]) -> bool:
    """병합 전 구조적 안전장치.

    같은 턴에서 새로 생긴 약한 노드끼리는 embedding/주변 구조가 우연히 비슷해도 바로
    병합하지 않는다. merge는 되돌리기 어렵기 때문에 안정성, 반복 지지, 공유 이웃을 요구한다.
    """
    if node_a.address_hash in new_hashes and node_b.address_hash in new_hashes:
        return False

    if node_a.stability_score < MIN_STABILITY_FOR_MERGE or node_b.stability_score < MIN_STABILITY_FOR_MERGE:
        return False

    shared_neighbors = (neighbors_a & neighbors_b) - {node_a.address_hash, node_b.address_hash}
    if len(shared_neighbors) < MIN_SHARED_NEIGHBORS_FOR_MERGE:
        return False

    direct_support = _direct_support_count(tg, node_a.address_hash, node_b.address_hash)
    if direct_support < MIN_SUPPORT_FOR_MERGE:
        return False

    return True


def _direct_support_count(tg: TempThoughtGraph, hash_a: str, hash_b: str) -> int:
    count = 0
    for edge in tg.get_edges_for_node(hash_a):
        if edge.is_temporary:
            continue
        if {edge.source_hash, edge.target_hash} != {hash_a, hash_b}:
            continue
        if edge.connect_type == "conflict":
            continue
        count += max(1, edge.support_count)
    return count
