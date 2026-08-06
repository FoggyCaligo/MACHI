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
    - 현재 seq에 존재하는 연속 구간만 과거 seq에서 proj한다.
    - proj의 인접 연결 중첩 밀도가 바뀌는 지점에서 segment를 나눈다.
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

    def _load_sequences(self) -> Iterable[list[str]]:
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
            if current_id is not None and row["input_id"] != current_id:
                yield current
                current = []
            current_id = row["input_id"]
            current.append(row["value"])
        if current_id is not None:
            yield current

    @staticmethod
    def _contains(sequence: list[str], candidate: tuple[str, ...]) -> bool:
        size = len(candidate)
        return any(
            tuple(sequence[i : i + size]) == candidate
            for i in range(len(sequence) - size + 1)
        )

    def _support(self, candidate: tuple[str, ...], prior: list[list[str]]) -> int:
        """후보 경로를 포함하는 서로 다른 과거 seq의 수."""
        return sum(1 for seq in prior if self._contains(seq, candidate))

    def _segment(
        self, alphs: list[str], prior: list[list[str]]
    ) -> tuple[list[str], list[SegmentEvidence]]:
        """현재 seq 위의 인접 연결 밀도를 기준으로 segment를 만든다.

        각 경계 i는 ``alphs[i] -> alphs[i + 1]`` 연결을 뜻한다.
        해당 연결이 과거의 서로 다른 seq에 몇 번 포함됐는지를 밀도로 삼는다.

        - 밀도가 0이면 두 alph를 묶지 않는다.
        - 양수 밀도가 연속해서 같으면 같은 segment로 묶는다.
        - 밀도가 달라지는 지점은 셀로판지의 색 농도가 달라지는 경계이므로 자른다.
        """
        n = len(alphs)
        if n == 1:
            item = SegmentEvidence(alphs[0], 0, 1, 0)
            return [item.text], [item]

        edge_support = [
            self._support((alphs[i], alphs[i + 1]), prior)
            for i in range(n - 1)
        ]

        evidence: list[SegmentEvidence] = []
        start = 0

        for boundary in range(n - 1):
            current_support = edge_support[boundary]
            next_support = edge_support[boundary + 1] if boundary + 1 < n - 1 else None

            should_cut = (
                current_support == 0
                or next_support is None
                or next_support != current_support
            )
            if not should_cut:
                continue

            end = boundary + 2 if current_support > 0 else boundary + 1
            if end > start:
                segment_support = current_support if end - start >= 2 else 0
                evidence.append(
                    SegmentEvidence("".join(alphs[start:end]), start, end, segment_support)
                )
                start = end

        while start < n:
            evidence.append(SegmentEvidence(alphs[start], start, start + 1, 0))
            start += 1

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
