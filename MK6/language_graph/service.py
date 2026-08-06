from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SegmentEvidence:
    text: str
    start: int
    end: int
    support: int


@dataclass(frozen=True)
class ProjectionResult:
    input_id: int
    text: str
    alphs: list[str]
    segments: list[str]
    evidence: list[SegmentEvidence]


class LanguageGraph:
    """alph/seq/proj 기반 언어 그래프.

    - 모든 Unicode code point를 alph로 동일 취급한다.
    - 한 턴 입력은 하나의 seq이며 매번 새로 저장한다.
    - 현재 seq 안에 같은 순서로 존재하는 연결만 과거 seq에서 proj한다.
    - 동일한 과거 input_id 층이 이어지는 동안만 하나의 segment로 묶는다.
    """

    def __init__(self, db_path: str | Path = "data/mk_language.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS alph (
                alph_id INTEGER PRIMARY KEY AUTOINCREMENT,
                value TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS seq (
                input_id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS seq_alph (
                input_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                alph_id INTEGER NOT NULL,
                PRIMARY KEY (input_id, position),
                FOREIGN KEY (input_id) REFERENCES seq(input_id),
                FOREIGN KEY (alph_id) REFERENCES alph(alph_id)
            );
            CREATE INDEX IF NOT EXISTS idx_seq_alph_alph ON seq_alph(alph_id);
            """
        )
        self.conn.commit()

    @staticmethod
    def split_alphs(text: str) -> list[str]:
        """공백/문장부호를 포함한 입력 전체를 alph로 분해한다."""
        return list(unicodedata.normalize("NFC", text))

    def process(self, text: str) -> ProjectionResult:
        if text == "":
            raise ValueError("빈 입력은 처리할 수 없습니다.")
        alphs = self.split_alphs(text)
        prior_sequences = list(self._load_sequences())
        segments, evidence = self._segment(alphs, prior_sequences)
        input_id = self._save_seq(text, alphs)
        return ProjectionResult(input_id, text, alphs, segments, evidence)

    def _load_sequences(self) -> Iterable[tuple[int, list[str]]]:
        rows = self.conn.execute(
            """
            SELECT sa.input_id, sa.position, a.value
            FROM seq_alph sa
            JOIN alph a ON a.alph_id = sa.alph_id
            ORDER BY sa.input_id, sa.position
            """
        )
        current_id: int | None = None
        current: list[str] = []
        for row in rows:
            row_input_id = int(row["input_id"])
            if current_id is not None and row_input_id != current_id:
                yield current_id, current
                current = []
            current_id = row_input_id
            current.append(row["value"])
        if current_id is not None:
            yield current_id, current

    @staticmethod
    def _contains(sequence: list[str], candidate: tuple[str, ...]) -> bool:
        size = len(candidate)
        return any(
            tuple(sequence[i : i + size]) == candidate
            for i in range(len(sequence) - size + 1)
        )

    def _support_ids(
        self,
        candidate: tuple[str, ...],
        prior: list[tuple[int, list[str]]],
    ) -> frozenset[int]:
        """현재 순서의 후보 연결을 포함하는 과거 input_id 층들."""
        return frozenset(
            input_id
            for input_id, sequence in prior
            if self._contains(sequence, candidate)
        )

    def _segment(
        self,
        alphs: list[str],
        prior: list[tuple[int, list[str]]],
    ) -> tuple[list[str], list[SegmentEvidence]]:
        """현재 입력 위에 투영된 seq 층의 동일 구간을 segment로 만든다.

        현재 입력의 각 인접 연결만 검사한다. 각 연결에는 그것을 실제로
        포함했던 과거 input_id 집합이 투영된다. 단순히 집합의 크기만 같은
        것으로는 이어 붙이지 않고, 집합 자체가 같을 때만 같은 색의 연속
        셀로판지 층으로 취급한다.
        """
        n = len(alphs)
        if n == 1:
            item = SegmentEvidence(alphs[0], 0, 1, 0)
            return [item.text], [item]

        edge_layers = [
            self._support_ids((alphs[i], alphs[i + 1]), prior)
            for i in range(n - 1)
        ]

        evidence: list[SegmentEvidence] = []
        start = 0

        while start < n:
            if start >= n - 1 or not edge_layers[start]:
                evidence.append(SegmentEvidence(alphs[start], start, start + 1, 0))
                start += 1
                continue

            layers = edge_layers[start]
            last_edge = start
            while last_edge + 1 < n - 1 and edge_layers[last_edge + 1] == layers:
                last_edge += 1

            end = last_edge + 2
            evidence.append(
                SegmentEvidence(
                    "".join(alphs[start:end]),
                    start,
                    end,
                    len(layers),
                )
            )
            start = end

        return [item.text for item in evidence], evidence

    def _save_seq(self, text: str, alphs: list[str]) -> int:
        cur = self.conn.execute("INSERT INTO seq(raw_text) VALUES (?)", (text,))
        input_id = int(cur.lastrowid)
        for position, value in enumerate(alphs):
            self.conn.execute("INSERT OR IGNORE INTO alph(value) VALUES (?)", (value,))
            alph_id = self.conn.execute(
                "SELECT alph_id FROM alph WHERE value = ?", (value,)
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO seq_alph(input_id, position, alph_id) VALUES (?, ?, ?)",
                (input_id, position, alph_id),
            )
        self.conn.commit()
        return input_id
