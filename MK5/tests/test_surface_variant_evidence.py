from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MK4.core.entities.edge import Edge
from MK4.core.entities.node import Node
from MK4.core.thinking import concept_merge, surface_variant_evidence
from MK4.core.thinking.temp_thought_graph import TempThoughtGraph


def _make_node(label: str, *, stability: float = 0.8, embedding: list[float] | None = None) -> Node:
    node_kind = "goal" if label == "goal" else "concept"
    return Node(
        address_hash=f"node::{label}",
        node_kind=node_kind,
        formation_source="ingest" if node_kind == "concept" else "system_policy",
        labels=[label],
        stability_score=stability,
        embedding=embedding,
    )


def _make_edge(source_hash: str, target_hash: str, *, support_count: int = 0) -> Edge:
    return Edge(
        edge_id=str(uuid.uuid4()),
        source_hash=source_hash,
        target_hash=target_hash,
        edge_family="concept",
        connect_type="neutral",
        provenance_source="lang_to_graph",
        support_count=support_count,
        is_temporary=False,
    )


class SurfaceVariantEvidenceTest(unittest.TestCase):
    def test_run_accumulates_existing_alias_evidence_edge(self) -> None:
        tg = TempThoughtGraph()
        tg.set_goal_node(_make_node("goal", embedding=None))

        node_a = _make_node("firefighter-a", embedding=[1.0, 0.0, 0.0])
        node_b = _make_node("firefighter-b", embedding=[1.0, 0.0, 0.0])
        shared = _make_node("shared-neighbor", embedding=[0.0, 1.0, 0.0])

        for node in (node_a, node_b, shared):
            tg.add_node(node)

        tg.add_edge(_make_edge(node_a.address_hash, shared.address_hash))
        tg.add_edge(_make_edge(node_b.address_hash, shared.address_hash))
        tg.reset_delta()

        first = surface_variant_evidence.run(tg)
        self.assertEqual(len(first), 1)

        evidence_edge = next(
            edge for edge in tg.all_edges() if edge.proposed_connect_type == "surface_variant_evidence"
        )
        self.assertEqual(evidence_edge.support_count, 1)
        self.assertEqual(evidence_edge.payload.get("observation_count"), 1)

        tg.reset_delta()
        second = surface_variant_evidence.run(tg)
        self.assertEqual(len(second), 1)

        evidence_edge = next(
            edge for edge in tg.all_edges() if edge.proposed_connect_type == "surface_variant_evidence"
        )
        self.assertEqual(evidence_edge.support_count, 2)
        self.assertEqual(evidence_edge.payload.get("observation_count"), 2)
        self.assertIn("embedding_similarity", evidence_edge.payload.get("evidence_types", []))
        self.assertIn("shared_structure", evidence_edge.payload.get("evidence_types", []))

    def test_concept_merge_rechecks_pair_when_alias_evidence_edge_is_added(self) -> None:
        tg = TempThoughtGraph()
        tg.set_goal_node(_make_node("goal", embedding=None))

        node_a = _make_node("alias-a", embedding=[1.0, 0.0, 0.0])
        node_b = _make_node("alias-b", embedding=[1.0, 0.0, 0.0])
        shared_1 = _make_node("shared-1", embedding=[0.0, 1.0, 0.0])
        shared_2 = _make_node("shared-2", embedding=[0.0, 0.0, 1.0])

        for node in (node_a, node_b, shared_1, shared_2):
            tg.add_node(node)

        tg.add_edge(_make_edge(node_a.address_hash, shared_1.address_hash))
        tg.add_edge(_make_edge(node_a.address_hash, shared_2.address_hash))
        tg.add_edge(_make_edge(node_b.address_hash, shared_1.address_hash))
        tg.add_edge(_make_edge(node_b.address_hash, shared_2.address_hash))
        tg.reset_delta()

        tg.mark_pair_checked(node_a.address_hash, node_b.address_hash)
        surface_variant_evidence.run(tg)
        merge_count = concept_merge.run(tg)

        self.assertEqual(merge_count, 1)
        self.assertTrue(
            tg.get_node(node_a.address_hash) is None or tg.get_node(node_b.address_hash) is None
        )


if __name__ == "__main__":
    unittest.main()

