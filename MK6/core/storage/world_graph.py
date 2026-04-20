"""WorldGraph — 세계그래프 영구 저장소 CRUD."""
from __future__ import annotations

import json
import struct
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

from ..entities.node import Node
from ..entities.edge import Edge
from ..entities.word_entry import WordEntry


# ── 직렬화 헬퍼 ──────────────────────────────────────────────────────────────

def _pack_embedding(embedding: list[float] | None) -> bytes | None:
    if embedding is None:
        return None
    return struct.pack(f"{len(embedding)}f", *embedding)


def _unpack_embedding(blob: bytes | None) -> list[float] | None:
    if blob is None:
        return None
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── 노드 ─────────────────────────────────────────────────────────────────────

def insert_node(conn: sqlite3.Connection, node: Node) -> None:
    conn.execute(
        """
        INSERT INTO nodes
            (address_hash, labels, is_abstract, node_kind, embedding,
             trust_score, stability_score, is_active, formation_source,
             payload, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node.address_hash,
            node.labels_json(),
            int(node.is_abstract),
            node.node_kind,
            _pack_embedding(node.embedding),
            node.trust_score,
            node.stability_score,
            int(node.is_active),
            node.formation_source,
            node.payload_json(),
            _iso(node.created_at),
            _iso(node.updated_at),
        ),
    )


def get_node(conn: sqlite3.Connection, address_hash: str) -> Node | None:
    row = conn.execute(
        "SELECT * FROM nodes WHERE address_hash = ?", (address_hash,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_node(row)


def update_node(conn: sqlite3.Connection, node: Node) -> None:
    conn.execute(
        """
        UPDATE nodes SET
            labels = ?, is_abstract = ?, node_kind = ?, embedding = ?,
            trust_score = ?, stability_score = ?, is_active = ?,
            formation_source = ?, payload = ?, updated_at = ?
        WHERE address_hash = ?
        """,
        (
            node.labels_json(),
            int(node.is_abstract),
            node.node_kind,
            _pack_embedding(node.embedding),
            node.trust_score,
            node.stability_score,
            int(node.is_active),
            node.formation_source,
            node.payload_json(),
            _iso(node.updated_at),
            node.address_hash,
        ),
    )


def deactivate_node(conn: sqlite3.Connection, address_hash: str) -> None:
    conn.execute(
        "UPDATE nodes SET is_active = 0, updated_at = ? WHERE address_hash = ?",
        (_iso(datetime.now(timezone.utc)), address_hash),
    )


def get_active_nodes(conn: sqlite3.Connection) -> list[Node]:
    rows = conn.execute(
        "SELECT * FROM nodes WHERE is_active = 1"
    ).fetchall()
    return [_row_to_node(r) for r in rows]


def _row_to_node(row: sqlite3.Row) -> Node:
    return Node(
        address_hash=row["address_hash"],
        node_kind=row["node_kind"],
        formation_source=row["formation_source"],
        labels=Node.labels_from_json(row["labels"]),
        is_abstract=bool(row["is_abstract"]),
        trust_score=row["trust_score"],
        stability_score=row["stability_score"],
        is_active=bool(row["is_active"]),
        embedding=_unpack_embedding(row["embedding"]),
        payload=Node.payload_from_json(row["payload"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


# ── 엣지 ─────────────────────────────────────────────────────────────────────

def insert_edge(conn: sqlite3.Connection, edge: Edge) -> None:
    conn.execute(
        """
        INSERT INTO edges
            (edge_id, source_hash, target_hash, edge_family, connect_type,
             proposed_connect_type, proposal_reason, translation_confidence,
             provenance_source, support_count, conflict_count,
             contradiction_pressure, trust_score, edge_weight,
             is_active, is_temporary, payload, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            edge.edge_id,
            edge.source_hash,
            edge.target_hash,
            edge.edge_family,
            edge.connect_type,
            edge.proposed_connect_type,
            edge.proposal_reason,
            edge.translation_confidence,
            edge.provenance_source,
            edge.support_count,
            edge.conflict_count,
            edge.contradiction_pressure,
            edge.trust_score,
            edge.edge_weight,
            int(edge.is_active),
            int(edge.is_temporary),
            edge.payload_json(),
            _iso(edge.created_at),
            _iso(edge.updated_at),
        ),
    )


def get_edge(conn: sqlite3.Connection, edge_id: str) -> Edge | None:
    row = conn.execute(
        "SELECT * FROM edges WHERE edge_id = ?", (edge_id,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_edge(row)


def update_edge(conn: sqlite3.Connection, edge: Edge) -> None:
    conn.execute(
        """
        UPDATE edges SET
            edge_family = ?, connect_type = ?,
            proposed_connect_type = ?, proposal_reason = ?,
            translation_confidence = ?, provenance_source = ?,
            support_count = ?, conflict_count = ?,
            contradiction_pressure = ?, trust_score = ?,
            edge_weight = ?, is_active = ?, is_temporary = ?,
            payload = ?, updated_at = ?
        WHERE edge_id = ?
        """,
        (
            edge.edge_family,
            edge.connect_type,
            edge.proposed_connect_type,
            edge.proposal_reason,
            edge.translation_confidence,
            edge.provenance_source,
            edge.support_count,
            edge.conflict_count,
            edge.contradiction_pressure,
            edge.trust_score,
            edge.edge_weight,
            int(edge.is_active),
            int(edge.is_temporary),
            edge.payload_json(),
            _iso(edge.updated_at),
            edge.edge_id,
        ),
    )


def get_edges_for_node(
    conn: sqlite3.Connection,
    address_hash: str,
    *,
    active_only: bool = True,
) -> list[Edge]:
    """노드에 연결된 모든 엣지(출발 또는 도착)를 반환한다."""
    clause = "AND is_active = 1" if active_only else ""
    rows = conn.execute(
        f"""
        SELECT * FROM edges
        WHERE (source_hash = ? OR target_hash = ?) {clause}
        """,
        (address_hash, address_hash),
    ).fetchall()
    return [_row_to_edge(r) for r in rows]


def _row_to_edge(row: sqlite3.Row) -> Edge:
    return Edge(
        edge_id=row["edge_id"],
        source_hash=row["source_hash"],
        target_hash=row["target_hash"],
        edge_family=row["edge_family"],
        connect_type=row["connect_type"],
        provenance_source=row["provenance_source"],
        proposed_connect_type=row["proposed_connect_type"],
        proposal_reason=row["proposal_reason"],
        translation_confidence=row["translation_confidence"],
        support_count=row["support_count"],
        conflict_count=row["conflict_count"],
        contradiction_pressure=row["contradiction_pressure"],
        trust_score=row["trust_score"],
        edge_weight=row["edge_weight"],
        is_active=bool(row["is_active"]),
        is_temporary=bool(row["is_temporary"]),
        payload=Edge.payload_from_json(row["payload"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


# ── 단어 ─────────────────────────────────────────────────────────────────────

def insert_word(conn: sqlite3.Connection, entry: WordEntry) -> None:
    conn.execute(
        """
        INSERT INTO words (word_id, surface_form, address_hash, language, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            entry.word_id,
            entry.surface_form,
            entry.address_hash,
            entry.language,
            _iso(entry.created_at),
        ),
    )


def get_word(conn: sqlite3.Connection, surface_form: str) -> WordEntry | None:
    row = conn.execute(
        "SELECT * FROM words WHERE surface_form = ?", (surface_form,)
    ).fetchone()
    if row is None:
        return None
    return _row_to_word(row)


def get_words_for_node(
    conn: sqlite3.Connection, address_hash: str
) -> list[WordEntry]:
    rows = conn.execute(
        "SELECT * FROM words WHERE address_hash = ?", (address_hash,)
    ).fetchall()
    return [_row_to_word(r) for r in rows]


def remap_words_to_node(
    conn: sqlite3.Connection,
    from_hashes: Iterable[str],
    to_hash: str,
) -> None:
    """Merge 시 여러 노드에 연결된 단어들을 하나의 노드로 일괄 재연결한다."""
    for h in from_hashes:
        conn.execute(
            "UPDATE words SET address_hash = ? WHERE address_hash = ?",
            (to_hash, h),
        )


def _row_to_word(row: sqlite3.Row) -> WordEntry:
    return WordEntry(
        word_id=row["word_id"],
        surface_form=row["surface_form"],
        address_hash=row["address_hash"],
        language=row["language"],
        created_at=_dt(row["created_at"]),
    )
