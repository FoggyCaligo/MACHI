"""LangToGraph 다대다 surface_form 해석 테스트."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from MK6.core.entities.node import Node
from MK6.core.entities.translated_graph import ConceptPointer
from MK6.core.entities.word_entry import WordEntry
from MK6.core.storage.db import open_db
from MK6.core.storage.world_graph import insert_node, insert_word
from MK6.core.translation.lang_to_graph import translate


def _make_node(address_hash: str | None = None, labels: list[str] | None = None) -> Node:
    now = datetime.now(timezone.utc)
    return Node(
        address_hash=address_hash or uuid.uuid4().hex[:32],
        node_kind="concept",
        formation_source="ingest",
        labels=labels or ["테스트"],
        trust_score=0.5,
        stability_score=0.5,
        is_active=True,
        embedding=[1.0, 0.0],
        created_at=now,
        updated_at=now,
    )


async def _embed(_: str) -> list[float]:
    return [1.0, 0.0]


def test_exact_match_returns_all_surface_candidates():
    conn = open_db(":memory:")
    try:
        cross_symbol = _make_node(labels=["십자가"])
        cross_motion = _make_node(labels=["교차 동작"])
        apple = _make_node(labels=["사과"])
        for node in [cross_symbol, cross_motion, apple]:
            insert_node(conn, node)

        now = datetime.now(timezone.utc)
        insert_word(conn, WordEntry(str(uuid.uuid4()), "cross", cross_symbol.address_hash, "en", now))
        insert_word(conn, WordEntry(str(uuid.uuid4()), "cross", cross_motion.address_hash, "en", now))
        insert_word(conn, WordEntry(str(uuid.uuid4()), "apple", apple.address_hash, "en", now))
        conn.commit()

        translated = asyncio.run(translate("cross apple", conn, _embed))

        pointers = [
            ref
            for ref in translated.nodes
            if isinstance(ref, ConceptPointer)
        ]
        assert {ptr.address_hash for ptr in pointers} == {
            cross_symbol.address_hash,
            cross_motion.address_hash,
            apple.address_hash,
        }

        edge_pairs = {
            (edge.source_ref.address_hash, edge.target_ref.address_hash)
            for edge in translated.edges
            if (
                isinstance(edge.source_ref, ConceptPointer)
                and isinstance(edge.target_ref, ConceptPointer)
            )
        }
        assert edge_pairs == {
            (cross_symbol.address_hash, apple.address_hash),
            (cross_motion.address_hash, apple.address_hash),
        }
    finally:
        conn.close()
