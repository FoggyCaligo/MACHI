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
    - proj의 중첩 밀도를 이용해 segment를 선택한다.
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
        return any(tuple(sequence[i : i + size]) == candidate for i in range(len(sequence) - size + 1))

    def _support(self, candidate: tuple[str, ...], prior: list[list[str]]) -> int:
        return sum(1 for seq in prior if self._contains(seq, candidate))

    def _segment(
        self, alphs: list[str], prior: list[list[str]]
    ) -> tuple[list[str], list[SegmentEvidence]]:
        n = len(alphs)
        # dp[i] = 0..i를 가장 잘 설명한 점수와 구간 목록
        dp: list[tuple[float, list[SegmentEvidence]] | None] = [None] * (n + 1)
        dp[0] = (0.0, [])

        for end in range(1, n + 1):
            best: tuple[float, list[SegmentEvidence]] | None = None
            for start in range(0, end):
                prev = dp[start]
                if prev is None:
                    continue
                length = end - start
                candidate = tuple(alphs[start:end])
                support = self._support(candidate, prior) if length >= 2 else 0

                # 단일 alph는 증거가 아니라 긴 segment로 덮이지 않는 경우의 fallback.
                if length == 1:
                    score = prev[0] - 0.25
                elif support > 0:
                    score = prev[0] + support * (length ** 2)
                else:
                    continue

                item = SegmentEvidence("".join(candidate), start, end, support)
                proposal = (score, [*prev[1], item])
                if best is None or proposal[0] > best[0]:
                    best = proposal
            dp[end] = best

        chosen = dp[n]
        if chosen is None:
            evidence = [SegmentEvidence(a, i, i + 1, 0) for i, a in enumerate(alphs)]
        else:
            evidence = chosen[1]
        return [item.text for item in evidence], evidence

    def _save_seq(self, text: str, alphs: list[str]) -> int:
        cur = self.conn.execute("INSERT INTO seq(raw_text) VALUES (?)", (text,))
        input_id = int(cur.lastrowid)
        for position, value in enumerate(alphs):
            self.conn.execute("INSERT OR IGNORE INTO alph(value) VALUES (?)", (value,))
            alph_id = self.conn.execute("SELECT alph_id FROM alph WHERE value = ?", (value,)).fetchone()[0]
            self.conn.execute(
                "INSERT INTO seq_alph(input_id, position, alph_id) VALUES (?, ?, ?)",
                (input_id, position, alph_id),
            )
        self.conn.commit()
        return input_id
