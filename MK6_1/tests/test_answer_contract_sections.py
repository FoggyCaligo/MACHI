from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MK6_1.core.entities.edge import Edge
from MK6_1.core.entities.node import Node
from MK6_1.core.entities.translated_graph import (
    ConceptPointer,
    LocalSubgraph,
    TranslatedEdge,
    TranslatedGraph,
)
from MK6_1.core.thinking.conclusion_graph import ConclusionGraph
from MK6_1.core.thinking.thought_engine import ConclusionView
from MK6_1.core.verbalization import build_answer_contract


class AnswerContractSectionsTest(unittest.TestCase):
    def test_build_answer_contract_splits_three_graph_sections(self) -> None:
        now = datetime.now(timezone.utc)
        input_node = Node(
            address_hash="input-hash",
            node_kind="concept",
            formation_source="ingest",
            labels=["신재용"],
            created_at=now,
            updated_at=now,
        )
        search_node = Node(
            address_hash="search-hash",
            node_kind="concept",
            formation_source="search",
            labels=["스물여섯이야"],
            created_at=now,
            updated_at=now,
        )
        conclusion_node = Node(
            address_hash="conclusion-hash",
            node_kind="concept",
            formation_source="search",
            labels=["소개"],
            created_at=now,
            updated_at=now,
        )

        translated = TranslatedGraph(
            nodes=[
                ConceptPointer(
                    address_hash=input_node.address_hash,
                    local_subgraph=LocalSubgraph(center_hash=input_node.address_hash, nodes=[input_node], edges=[]),
                    importance=1.0,
                    resolution_source="exact_match",
                )
            ],
            edges=[
                TranslatedEdge(
                    source_ref=ConceptPointer(
                        address_hash=input_node.address_hash,
                        local_subgraph=LocalSubgraph(center_hash=input_node.address_hash, nodes=[input_node], edges=[]),
                        importance=1.0,
                        resolution_source="exact_match",
                    ),
                    target_ref=ConceptPointer(
                        address_hash=search_node.address_hash,
                        local_subgraph=LocalSubgraph(center_hash=search_node.address_hash, nodes=[search_node], edges=[]),
                        importance=0.8,
                        resolution_source="semantic_local_candidate",
                    ),
                    edge_family="concept",
                    connect_type="neutral",
                    confidence=0.7,
                )
            ],
            source="안녕? 난 신재용 이야.",
        )

        conclusion_edge = Edge(
            edge_id="conclusion-edge",
            source_hash=input_node.address_hash,
            target_hash=conclusion_node.address_hash,
            edge_family="relation",
            connect_type="flow",
            provenance_source="search",
            edge_weight=0.9,
            trust_score=0.8,
            created_at=now,
            updated_at=now,
        )
        search_edge = Edge(
            edge_id="search-edge",
            source_hash=input_node.address_hash,
            target_hash=search_node.address_hash,
            edge_family="concept",
            connect_type="neutral",
            provenance_source="search",
            edge_weight=0.6,
            trust_score=0.5,
            created_at=now,
            updated_at=now,
        )
        conclusion_graph = ConclusionGraph(
            graph_id="g1",
            input_hashes={input_node.address_hash},
            goal_hashes={"goal"},
            node_hashes={input_node.address_hash, conclusion_node.address_hash},
            edge_ids={conclusion_edge.edge_id},
            core_hashes={conclusion_node.address_hash},
        )
        conclusion = ConclusionView(
            nodes=[input_node, search_node, conclusion_node],
            edges=[conclusion_edge, search_edge],
            goal_hash="goal",
            had_empty_slots=False,
            loop_count=1,
            user_input="안녕? 난 신재용 이야.",
            key_hashes={input_node.address_hash},
            search_node_hashes={search_node.address_hash},
            selected_graphs=[conclusion_graph],
        )

        contract = build_answer_contract(conclusion, translated)

        self.assertEqual(contract.input_graph.speaker, "user")
        self.assertEqual(contract.conclusion_graph.speaker, "system")
        self.assertEqual(contract.search_graph.speaker, "external")
        self.assertEqual(contract.input_graph.focus.primary, ["신재용"])
        self.assertEqual(contract.conclusion_graph.focus.primary, ["소개"])
        self.assertEqual(contract.search_graph.focus.primary, ["스물여섯이야"])

    def test_build_answer_contract_hides_empty_conclusion_graph(self) -> None:
        now = datetime.now(timezone.utc)
        input_node = Node(
            address_hash="input-hash",
            node_kind="concept",
            formation_source="ingest",
            labels=["input"],
            created_at=now,
            updated_at=now,
        )

        translated = TranslatedGraph(
            nodes=[
                ConceptPointer(
                    address_hash=input_node.address_hash,
                    local_subgraph=LocalSubgraph(center_hash=input_node.address_hash, nodes=[input_node], edges=[]),
                    importance=1.0,
                    resolution_source="exact_match",
                )
            ],
            edges=[],
            source="input",
        )

        empty_conclusion_graph = ConclusionGraph(
            graph_id="g-empty",
            input_hashes={input_node.address_hash},
            goal_hashes={"goal"},
            node_hashes={input_node.address_hash},
            edge_ids=set(),
            core_hashes={input_node.address_hash},
        )
        conclusion = ConclusionView(
            nodes=[input_node],
            edges=[],
            goal_hash="goal",
            had_empty_slots=False,
            loop_count=1,
            user_input="input",
            key_hashes={input_node.address_hash},
            selected_graphs=[empty_conclusion_graph],
        )

        contract = build_answer_contract(conclusion, translated)

        self.assertEqual(contract.conclusion_graph.focus.primary, [])
        self.assertEqual(contract.conclusion_graph.focus.supporting, [])
        self.assertEqual(contract.conclusion_graph.frames, [])


if __name__ == "__main__":
    unittest.main()
