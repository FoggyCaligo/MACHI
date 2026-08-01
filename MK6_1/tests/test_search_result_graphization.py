from __future__ import annotations

import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MK6_1.core.entities.node import Node
from MK6_1.core.entities.translated_graph import EmptySlot
from MK6_1.core.entities.word_entry import WordEntry
from MK6_1.core.storage.db import close_db, open_db
from MK6_1.core.storage.world_graph import (
    get_edges_for_node,
    get_node,
    insert_node,
    insert_word,
)
from MK6_1.core.thinking.temp_thought_graph import TempThoughtGraph
from MK6_1.core.thinking.thought_engine import ThoughtEngine
from MK6_1.core.utils.hash_resolver import compute_hash, normalize_text
from MK6_1.tools.search_client import SearchBundle, SearchResult


class SearchResultGraphizationTest(unittest.IsolatedAsyncioTestCase):
    async def test_fill_empty_slots_graphizes_search_results_and_commits_edges(self) -> None:
        queries: list[str] = []

        async def fake_embed(text: str) -> list[float]:
            normalized = normalize_text(text)
            if normalized == "korea":
                return [1.0, 0.0, 0.0]
            if normalized == "seoul":
                return [0.0, 1.0, 0.0]
            if normalized == "capital":
                return [0.0, 0.0, 1.0]
            return [1.0, 1.0, 1.0]

        async def fake_search(query: str) -> SearchBundle:
            queries.append(query)
            return SearchBundle(
                query=query,
                results=[
                    SearchResult(
                        query=query,
                        source="unit",
                        title="korea",
                        url="https://example.com/korea",
                        snippet="seoul capital",
                        rank=1,
                    )
                ],
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            conn = open_db(str(Path(tmpdir) / "test.db"))
            try:
                goal = Node(
                    address_hash="goal-test-node",
                    node_kind="goal",
                    formation_source="system_policy",
                    labels=["Goal"],
                )
                insert_node(conn, goal)

                korea_hash = compute_hash("korea")
                korea_node = Node(
                    address_hash=korea_hash,
                    node_kind="concept",
                    formation_source="ingest",
                    labels=["korea"],
                    embedding=[1.0, 0.0, 0.0],
                )
                insert_node(conn, korea_node)
                insert_word(
                    conn,
                    WordEntry(
                        word_id=str(uuid.uuid4()),
                        surface_form=normalize_text("korea"),
                        address_hash=korea_hash,
                        language="en",
                        created_at=korea_node.created_at,
                    ),
                )
                conn.commit()

                tg = TempThoughtGraph()
                tg.set_goal_node(goal)
                tg.add_node(korea_node)
                tg._empty_slots = [EmptySlot(concept_hint="seoul", importance=0.9)]

                engine = ThoughtEngine(
                    conn=conn,
                    embed_fn=fake_embed,
                    search_fn=fake_search,
                    goal_node=goal,
                )

                with patch(
                    "MK6_1.core.thinking.thought_engine.extract_relation_candidates",
                    return_value=[],
                ):
                    searched_hashes = await engine._fill_empty_slots(
                        tg,
                        user_input="tell me about seoul in korea",
                        concept_hashes={korea_hash},
                        active_local_hashes={korea_hash},
                        searched_queries=set(),
                    )
                engine._commit_new_content(tg)

                self.assertEqual(queries, ["seoul"])
                self.assertIn(compute_hash("seoul"), searched_hashes)
                self.assertIsNotNone(get_node(conn, compute_hash("seoul")))
                self.assertIsNotNone(get_node(conn, compute_hash("capital")))

                committed_edges = get_edges_for_node(conn, korea_hash, active_only=True)
                connected_targets = {edge.target_hash for edge in committed_edges if edge.provenance_source == "search"}
                self.assertIn(compute_hash("seoul"), connected_targets)
                self.assertIn(compute_hash("capital"), connected_targets)
            finally:
                close_db(conn)

    async def test_fill_empty_slots_uses_per_slot_queries_instead_of_combined_sentence_query(self) -> None:
        queries: list[str] = []

        async def fake_embed(text: str) -> list[float]:
            return [1.0, 0.0, 0.0]

        async def fake_search(query: str) -> SearchBundle:
            queries.append(query)
            return SearchBundle(query=query, results=[])

        with tempfile.TemporaryDirectory() as tmpdir:
            conn = open_db(str(Path(tmpdir) / "test.db"))
            try:
                goal = Node(
                    address_hash="goal-test-node",
                    node_kind="goal",
                    formation_source="system_policy",
                    labels=["Goal"],
                )
                insert_node(conn, goal)

                tg = TempThoughtGraph()
                tg.set_goal_node(goal)
                tg._empty_slots = [
                    EmptySlot(concept_hint="프로젝트야", importance=0.9),
                    EmptySlot(concept_hint="개인적", importance=0.8),
                    EmptySlot(concept_hint="아니", importance=0.7),
                ]

                engine = ThoughtEngine(
                    conn=conn,
                    embed_fn=fake_embed,
                    search_fn=fake_search,
                    goal_node=goal,
                )

                with patch(
                    "MK6_1.core.thinking.thought_engine.extract_relation_candidates",
                    return_value=[],
                ):
                    await engine._fill_empty_slots(
                        tg,
                        user_input="개인적 프로젝트야 아니",
                        searched_queries=set(),
                    )

                self.assertEqual(queries, ["프로젝트", "개인적"])
            finally:
                close_db(conn)


if __name__ == "__main__":
    unittest.main()
