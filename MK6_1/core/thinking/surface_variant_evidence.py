"""SurfaceVariantEvidence - accumulate language-neutral alias evidence edges."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations

from ..entities.edge import Edge
from ..entities.node import Node
from .concept_differentiation import composite_score
from .temp_thought_graph import TempThoughtGraph


SURFACE_VARIANT_SCORE_THRESHOLD = 0.94
SURFACE_VARIANT_MIN_SHARED_NEIGHBORS = 1
SURFACE_VARIANT_EDGE_WEIGHT = 0.35
SURFACE_VARIANT_TRUST_SCORE = 0.45


@dataclass(frozen=True, slots=True)
class SurfaceVariantEvidence:
    source_hash: str
    target_hash: str
    score: float
    shared_neighbor_count: int


def run(tg: TempThoughtGraph) -> list[SurfaceVariantEvidence]:
    """Accumulate alias evidence from embedding similarity and shared structure."""
    nodes = [
        n for n in tg.all_nodes()
        if n.embedding is not None
        and n.is_active
        and not n.is_abstract
        and n.address_hash != tg.goal_hash
    ]
    if len(nodes) < 2:
        return []

    neighbor_cache = {
        n.address_hash: tg.neighbor_hashes(n.address_hash)
        for n in nodes
    }

    results: list[SurfaceVariantEvidence] = []
    for node_a, node_b in combinations(nodes, 2):
        hash_a, hash_b = node_a.address_hash, node_b.address_hash
        if tg.get_node(hash_a) is None or tg.get_node(hash_b) is None:
            continue

        neighbors_a = neighbor_cache[hash_a]
        neighbors_b = neighbor_cache[hash_b]
        shared_neighbors = (neighbors_a & neighbors_b) - {hash_a, hash_b}
        if len(shared_neighbors) < SURFACE_VARIANT_MIN_SHARED_NEIGHBORS:
            continue

        score = composite_score(node_a, node_b, neighbors_a, neighbors_b)
        if score < SURFACE_VARIANT_SCORE_THRESHOLD:
            continue

        edge = _existing_support_edge(tg, hash_a, hash_b)
        if edge is None:
            edge = _make_support_edge(
                node_a,
                node_b,
                score=score,
                shared_neighbor_count=len(shared_neighbors),
            )
            tg.add_edge(edge)
        else:
            _accumulate_support_edge(
                tg,
                edge,
                score=score,
                shared_neighbor_count=len(shared_neighbors),
            )

        results.append(SurfaceVariantEvidence(
            source_hash=hash_a,
            target_hash=hash_b,
            score=score,
            shared_neighbor_count=len(shared_neighbors),
        ))

    return results


def _existing_support_edge(tg: TempThoughtGraph, hash_a: str, hash_b: str) -> Edge | None:
    for edge in tg.get_edges_for_node(hash_a):
        if {edge.source_hash, edge.target_hash} != {hash_a, hash_b}:
            continue
        if edge.is_temporary:
            continue
        if edge.connect_type == "conflict":
            continue
        if edge.proposed_connect_type == "surface_variant_evidence":
            return edge
    return None


def _accumulate_support_edge(
    tg: TempThoughtGraph,
    edge: Edge,
    *,
    score: float,
    shared_neighbor_count: int,
) -> None:
    payload = dict(edge.payload)
    evidence_types = set(payload.get("evidence_types") or [])
    evidence_types.update({"embedding_similarity", "shared_structure"})
    payload["alias_evidence"] = True
    payload["evidence_types"] = sorted(evidence_types)
    payload["composite_score"] = max(float(payload.get("composite_score") or 0.0), score)
    payload["shared_neighbor_count"] = max(int(payload.get("shared_neighbor_count") or 0), shared_neighbor_count)
    payload["observation_count"] = int(payload.get("observation_count") or max(1, edge.support_count)) + 1
    payload["alias_confidence"] = min(
        1.0,
        max(float(payload.get("alias_confidence") or 0.0), score * 0.75) + 0.08,
    )
    edge.payload = payload
    edge.support_count += 1
    edge.edge_weight = min(0.9, max(edge.edge_weight, SURFACE_VARIANT_EDGE_WEIGHT) + 0.08)
    edge.trust_score = min(0.95, max(edge.trust_score, SURFACE_VARIANT_TRUST_SCORE, score * 0.5))
    edge.touch()
    tg.update_edge(edge)


def _make_support_edge(
    node_a: Node,
    node_b: Node,
    *,
    score: float,
    shared_neighbor_count: int,
) -> Edge:
    now = datetime.now(timezone.utc)
    return Edge(
        edge_id=str(uuid.uuid4()),
        source_hash=node_a.address_hash,
        target_hash=node_b.address_hash,
        edge_family="concept",
        connect_type="neutral",
        edge_weight=SURFACE_VARIANT_EDGE_WEIGHT,
        trust_score=SURFACE_VARIANT_TRUST_SCORE,
        support_count=1,
        provenance_source="differentiation",
        proposed_connect_type="surface_variant_evidence",
        proposal_reason="language-neutral alias evidence from embedding/shared-neighbor overlap",
        payload={
            "alias_evidence": True,
            "evidence_types": ["embedding_similarity", "shared_structure"],
            "composite_score": score,
            "shared_neighbor_count": shared_neighbor_count,
            "observation_count": 1,
            "alias_confidence": score * 0.75,
        },
        is_temporary=False,
        created_at=now,
        updated_at=now,
    )
