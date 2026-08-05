from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MK4.core.entities.edge import Edge
from MK4.core.entities.node import Node
from MK4.core.entities.translated_graph import ConceptPointer, LocalSubgraph, TranslatedGraph
from MK4.core.thinking.claim_graph import (
    AssertionState,
    ClaimAssertion,
    apply_user_correction_policy,
    build_claim_conflict_graph,
)
from MK4.core.thinking.temp_thought_graph import TempThoughtGraph
from MK4.core.utils.hash_resolver import ANCHOR_ASSISTANT, ANCHOR_USER, compute_hash


class ClaimGraphCorrectionTest(unittest.TestCase):
    def test_user_correction_policy_adds_generic_conflict_and_support_edges(self) -> None:
        now = datetime.now(timezone.utc)
        subject_hash = compute_hash("홍길동")
        wrong_hash = compute_hash("의사")
        right_hash = compute_hash("개발자")

        subject = Node(
            address_hash=subject_hash,
            node_kind="concept",
            formation_source="ingest",
            labels=["홍길동"],
            created_at=now,
            updated_at=now,
        )
        wrong = Node(
            address_hash=wrong_hash,
            node_kind="concept",
            formation_source="ingest",
            labels=["의사"],
            created_at=now,
            updated_at=now,
        )
        right = Node(
            address_hash=right_hash,
            node_kind="concept",
            formation_source="ingest",
            labels=["개발자"],
            created_at=now,
            updated_at=now,
        )

        previous_edge = Edge(
            edge_id="previous-edge",
            source_hash=subject_hash,
            target_hash=wrong_hash,
            edge_family="relation",
            connect_type="flow",
            provenance_source="model_assertion",
            proposed_connect_type="assistant_assertion",
            support_count=1,
            trust_score=0.9,
            edge_weight=0.9,
            created_at=now,
            updated_at=now,
        )

        tg = TempThoughtGraph()
        tg.add_node(subject)
        tg.add_node(wrong)
        tg.add_node(right)
        tg.add_edge(previous_edge)

        translated = TranslatedGraph(
            nodes=[
                ConceptPointer(
                    address_hash=subject_hash,
                    local_subgraph=LocalSubgraph(center_hash=subject_hash, nodes=[subject], edges=[]),
                    importance=1.0,
                    resolution_source="exact_match",
                ),
                ConceptPointer(
                    address_hash=wrong_hash,
                    local_subgraph=LocalSubgraph(center_hash=wrong_hash, nodes=[wrong], edges=[]),
                    importance=0.8,
                    resolution_source="exact_match",
                ),
                ConceptPointer(
                    address_hash=right_hash,
                    local_subgraph=LocalSubgraph(center_hash=right_hash, nodes=[right], edges=[]),
                    importance=0.8,
                    resolution_source="exact_match",
                ),
            ],
            edges=[],
            source="홍길동 의사 개발자",
        )

        previous_state = AssertionState(
            source_role="assistant",
            source_hash=ANCHOR_ASSISTANT,
            key_hashes={subject_hash},
            ref_hashes={wrong_hash},
            assertions=[
                ClaimAssertion(
                    assertion_id="assistant-assertion",
                    source_hash=ANCHOR_ASSISTANT,
                    source_role="assistant",
                    subject_hashes={subject_hash},
                    object_hashes={wrong_hash},
                    edge_ids={previous_edge.edge_id},
                    provenance="assistant_statement",
                )
            ],
            edge_ids={previous_edge.edge_id},
        )

        assertion = apply_user_correction_policy(
            tg,
            translated,
            previous_state,
            subject_binding_hashes={subject_hash},
        )

        self.assertIsNotNone(assertion)

        conflict_edges = [
            edge for edge in tg.get_edges_for_node(subject_hash)
            if edge.proposed_connect_type == "user_correction_conflict"
        ]
        support_edges = [
            edge for edge in tg.get_edges_for_node(subject_hash)
            if edge.proposed_connect_type == "user_assertion"
        ]

        self.assertTrue(any(edge.target_hash == wrong_hash for edge in conflict_edges))
        self.assertTrue(any(edge.target_hash == right_hash for edge in support_edges))

        updated_previous = tg.get_edge(previous_edge.edge_id)
        assert updated_previous is not None
        self.assertGreaterEqual(updated_previous.conflict_count, 1)
        self.assertLess(updated_previous.trust_score, 0.9)

        claim_conflict_graph, _ = build_claim_conflict_graph(
            tg,
            translated,
            previous_state,
            subject_binding_hashes={subject_hash},
        )
        self.assertIsNotNone(claim_conflict_graph)
        self.assertIn(ANCHOR_USER, claim_conflict_graph.node_hashes)


if __name__ == "__main__":
    unittest.main()

