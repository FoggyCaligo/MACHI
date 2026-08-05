"""Conservatively merge concept nodes only when evidence has accumulated."""
from __future__ import annotations

from itertools import combinations

from .concept_differentiation import composite_score
from .temp_thought_graph import TempThoughtGraph


MERGE_THRESHOLD = 0.985
MIN_STABILITY_FOR_MERGE = 0.65
MIN_SHARED_NEIGHBORS_FOR_MERGE = 2
MIN_SUPPORT_FOR_MERGE = 2


def run(tg: TempThoughtGraph) -> int:
    """Inspect node pairs inside the temporary graph and merge only strong matches."""
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
    modified_hashes = (
        set(delta.added_nodes)
        | set(delta.modified_nodes)
        | _edge_touched_hashes(tg)
    )
    new_hashes = set(delta.added_nodes)

    for node_a, node_b in combinations(nodes, 2):
        hash_a, hash_b = node_a.address_hash, node_b.address_hash

        if tg.get_node(hash_a) is None or tg.get_node(hash_b) is None:
            continue

        if hash_a not in modified_hashes and hash_b not in modified_hashes:
            if tg.is_pair_checked(hash_a, hash_b):
                continue

        tg.mark_pair_checked(hash_a, hash_b)

        neighbors_a = neighbor_cache[hash_a] - {hash_b}
        neighbors_b = neighbor_cache[hash_b] - {hash_a}
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


def _is_merge_allowed(
    tg: TempThoughtGraph,
    node_a,
    node_b,
    neighbors_a: set[str],
    neighbors_b: set[str],
    new_hashes: set[str],
) -> bool:
    """Require stability, shared structure, and repeated support before merge."""
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
        if edge.proposed_connect_type == "surface_variant_evidence":
            count += _alias_evidence_support(edge)
            continue
        count += max(1, edge.support_count)
    return count


def _edge_touched_hashes(tg: TempThoughtGraph) -> set[str]:
    delta = tg.current_delta()
    edge_ids = set(delta.added_edges) | set(delta.modified_edges)
    touched: set[str] = set()
    for edge_id in edge_ids:
        edge = tg.get_edge(edge_id)
        if edge is None:
            continue
        touched.add(edge.source_hash)
        touched.add(edge.target_hash)
    return touched


def _alias_evidence_support(edge) -> int:
    payload = edge.payload or {}
    observation_count = int(payload.get("observation_count") or max(1, edge.support_count))
    shared_neighbor_count = int(payload.get("shared_neighbor_count") or 0)
    alias_confidence = float(payload.get("alias_confidence") or 0.0)

    support = 1
    if shared_neighbor_count >= 2 and alias_confidence >= 0.7:
        support += 1
    if observation_count >= 2:
        support += 1
    if observation_count >= 3:
        support += 1
    return support
