from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).with_name("lang_graph.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS alph_nodes (
    alph TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS seq_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    source_alph TEXT NOT NULL,
    target_alph TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_alph) REFERENCES alph_nodes(alph),
    FOREIGN KEY (target_alph) REFERENCES alph_nodes(alph)
);

CREATE INDEX IF NOT EXISTS idx_seq_edges_input_position
ON seq_edges (input_id, position);
"""


@dataclass(slots=True)
class SegmentCandidate:
    text: str
    score: int
    length: int


class LanguageGraph:
    """Character-path language graph with substring overlap segmentation."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def segment_text(self, text: str) -> list[str]:
        """Segment text from current history, then ingest the new input."""
        normalized = str(text)
        if not normalized:
            return []

        segments = self._segment_from_history(normalized)
        self._ingest(normalized)
        return segments

    def _segment_from_history(self, text: str) -> list[str]:
        best: list[SegmentCandidate | None] = [None] * (len(text) + 1)
        best[len(text)] = SegmentCandidate("", 0, 0)

        for start in range(len(text) - 1, -1, -1):
            fallback = best[start + 1]
            assert fallback is not None
            best_choice = SegmentCandidate(
                text=text[start],
                score=fallback.score,
                length=1 + fallback.length,
            )
            best_next = start + 1

            for end in range(start + 2, len(text) + 1):
                piece = text[start:end]
                count = self._count_substring_occurrences(piece)
                if count == 0:
                    continue

                candidate_next = best[end]
                assert candidate_next is not None
                candidate_score = fallback_score = candidate_next.score + (len(piece) * count)
                candidate_length = candidate_next.length + 1

                if candidate_score > best_choice.score:
                    best_choice = SegmentCandidate(piece, candidate_score, candidate_length)
                    best_next = end
                    continue

                if candidate_score == best_choice.score:
                    current_len = len(best_choice.text)
                    if len(piece) > current_len:
                        best_choice = SegmentCandidate(piece, candidate_score, candidate_length)
                        best_next = end
                    elif len(piece) == current_len and candidate_length < best_choice.length:
                        best_choice = SegmentCandidate(piece, candidate_score, candidate_length)
                        best_next = end

            best[start] = SegmentCandidate(
                text=f"{best_choice.text}|{best_next}",
                score=best_choice.score,
                length=best_choice.length,
            )

        segments: list[str] = []
        index = 0
        while index < len(text):
            marker = best[index]
            assert marker is not None
            piece, raw_next = marker.text.rsplit("|", 1)
            next_index = int(raw_next)
            segments.append(piece)
            index = next_index
        return segments

    def _count_substring_occurrences(self, piece: str) -> int:
        if len(piece) < 2:
            return 0

        input_ids = [
            row["input_id"]
            for row in self.conn.execute(
                "SELECT DISTINCT input_id FROM seq_edges ORDER BY input_id"
            ).fetchall()
        ]
        if not input_ids:
            return 0

        target_chars = list(piece)
        count = 0
        for input_id in input_ids:
            rows = self.conn.execute(
                """
                SELECT position, source_alph, target_alph
                FROM seq_edges
                WHERE input_id = ?
                ORDER BY position
                """,
                (input_id,),
            ).fetchall()
            if not rows:
                continue
            chars = [rows[0]["source_alph"]]
            chars.extend(row["target_alph"] for row in rows)
            for start in range(0, len(chars) - len(target_chars) + 1):
                if chars[start:start + len(target_chars)] == target_chars:
                    count += 1
        return count

    def _ingest(self, text: str) -> None:
        alphs = list(text)
        self.conn.executemany(
            "INSERT OR IGNORE INTO alph_nodes(alph) VALUES (?)",
            ((alph,) for alph in alphs),
        )

        input_id = f"input-{uuid.uuid4()}"
        self.conn.executemany(
            """
            INSERT INTO seq_edges(input_id, position, source_alph, target_alph)
            VALUES (?, ?, ?, ?)
            """,
            (
                (input_id, position, alphs[position], alphs[position + 1])
                for position in range(len(alphs) - 1)
            ),
        )
        self.conn.commit()


def segment_text(text: str, db_path: str | Path = DEFAULT_DB_PATH) -> list[str]:
    """Importable helper used by other MK6 modules."""
    graph = LanguageGraph(db_path)
    try:
        return graph.segment_text(text)
    finally:
        graph.close()
