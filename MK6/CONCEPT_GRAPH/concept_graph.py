from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..LANG_GRAPH import segment_text


DEFAULT_DB_PATH = Path(__file__).with_name("concept_graph.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS concept_nodes (
    address TEXT PRIMARY KEY,
    mention_count INTEGER NOT NULL DEFAULT 0,
    last_seen_order INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS concept_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_text TEXT NOT NULL,
    segment TEXT NOT NULL,
    segment_order INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(slots=True)
class ConceptGraphResult:
    text: str
    segments: list[str]
    concepts: list[dict[str, Any]]


def analyze_text(text: str, db_path: str | Path = DEFAULT_DB_PATH) -> ConceptGraphResult:
    """Minimal concept-graph consumer that reuses LANG_GRAPH segmentation."""
    segments = segment_text(text)
    _store_concepts(text, segments, Path(db_path))
    concepts = [
        {
            "address": segment,
            "kind": "segment",
            "order": index,
        }
        for index, segment in enumerate(segments)
    ]
    return ConceptGraphResult(text=text, segments=segments, concepts=concepts)


def initialize(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    conn = sqlite3.connect(Path(db_path))
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _store_concepts(text: str, segments: list[str], db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        for index, segment in enumerate(segments):
            conn.execute(
                """
                INSERT INTO concept_nodes(address, mention_count, last_seen_order)
                VALUES (?, 1, ?)
                ON CONFLICT(address) DO UPDATE SET
                    mention_count = mention_count + 1,
                    last_seen_order = excluded.last_seen_order,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (segment, index),
            )
            conn.execute(
                """
                INSERT INTO concept_events(input_text, segment, segment_order)
                VALUES (?, ?, ?)
                """,
                (text, segment, index),
            )
        conn.commit()
    finally:
        conn.close()
