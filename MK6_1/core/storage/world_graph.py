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


def get_edge_by_endpoints(
    conn: sqlite3.Connection,
    source_hash: str,
    target_hash: str,
) -> Edge | None:
    """source → target 방향의 active 엣지를 조회한다. 여러 개면 첫 번째 반환."""
    row = conn.execute(
        """
        SELECT * FROM edges
        WHERE source_hash = ? AND target_hash = ? AND is_active = 1
        LIMIT 1
        """,
        (source_hash, target_hash),
    ).fetchone()
    if row is None:
        return None
    return _row_to_edge(row)


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


# ── 단어/표면형 링크 ─────────────────────────────────────────────────────────

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


def get_words_for_surface(
    conn: sqlite3.Connection,
    surface_form: str,
) -> list[WordEntry]:
    """surface_form에 연결된 모든 WordEntry를 반환한다.

    words는 다대다 링크 집합이므로 surface_form 단독으로 단일 노드를
    결정하지 않는다. 호출자는 반환된 후보들을 그래프 구조에서 처리해야 한다.
    """
    rows = conn.execute(
        """
        SELECT * FROM words
        WHERE surface_form = ?
        ORDER BY created_at ASC, word_id ASC
        """,
        (surface_form,),
    ).fetchall()
    return [_row_to_word(r) for r in rows]


def word_link_exists(
    conn: sqlite3.Connection,
    surface_form: str,
    address_hash: str,
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM words
        WHERE surface_form = ? AND address_hash = ?
        LIMIT 1
        """,
        (surface_form, address_hash),
    ).fetchone()
    return row is not None


def get_words_for_node(
    conn: sqlite3.Connection, address_hash: str
) -> list[WordEntry]:
    rows = conn.execute(
        """
        SELECT * FROM words
        WHERE address_hash = ?
        ORDER BY created_at ASC, word_id ASC
        """,
        (address_hash,),
    ).fetchall()
    return [_row_to_word(r) for r in rows]


def remap_words_to_node(
    conn: sqlite3.Connection,
    from_hashes: Iterable[str],
    to_hash: str,
) -> None:
    """Merge 시 여러 노드에 연결된 표면형 링크를 생존 노드로 재연결한다.

    다대다 구조에서는 이미 같은 surface_form → to_hash 링크가 존재할 수 있다.
    이 경우 from_hash 쪽 링크를 삭제해 (surface_form, address_hash) 중복을
    만들지 않고 링크 집합을 정규화한다.
    """
    for h in from_hashes:
        rows = conn.execute(
            "SELECT * FROM words WHERE address_hash = ?",
            (h,),
        ).fetchall()
        for row in rows:
            surface_form = row["surface_form"]
            word_id = row["word_id"]
            duplicate = conn.execute(
                """
                SELECT 1 FROM words
                WHERE surface_form = ? AND address_hash = ? AND word_id <> ?
                LIMIT 1
                """,
                (surface_form, to_hash, word_id),
            ).fetchone()
            if duplicate is not None:
                conn.execute(
                    "DELETE FROM words WHERE word_id = ?",
                    (word_id,),
                )
            else:
                conn.execute(
                    "UPDATE words SET address_hash = ? WHERE word_id = ?",
                    (to_hash, word_id),
                )


def _row_to_word(row: sqlite3.Row) -> WordEntry:
    return WordEntry(
        word_id=row["word_id"],
        surface_form=row["surface_form"],
        address_hash=row["address_hash"],
        language=row["language"],
        created_at=_dt(row["created_at"]),
    )
