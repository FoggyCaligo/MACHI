from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from core.entities.edge import Edge
from storage.repositories.edge_repository import EdgeRepository
from storage.sqlite.common import as_bool, dumps_json, fetch_all, fetch_one, loads_json, placeholders


class SqliteEdgeRepository(EdgeRepository):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ping(self) -> None:
        self.connection.execute("SELECT 1").fetchone()

    def add(self, edge: Edge) -> Edge:
        cursor = self.connection.execute(
            """
            INSERT INTO edges (
                edge_uid, source_node_id, target_node_id, edge_type, relation_detail_json,
                edge_weight, trust_score, support_count, conflict_count,
                contradiction_pressure, revision_candidate_flag, created_from_event_id,
                last_supported_at, last_conflicted_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge.edge_uid,
                edge.source_node_id,
                edge.target_node_id,
                edge.edge_type,
                dumps_json(edge.relation_detail),
                edge.edge_weight,
                edge.trust_score,
                edge.support_count,
                edge.conflict_count,
                edge.contradiction_pressure,
                int(edge.revision_candidate_flag),
                edge.created_from_event_id,
                edge.last_supported_at,
                edge.last_conflicted_at,
                int(edge.is_active),
            ),
        )
        return self.get_by_id(int(cursor.lastrowid)) or edge

    def get_by_id(self, edge_id: int) -> Edge | None:
        row = fetch_one(self.connection, "SELECT * FROM edges WHERE id = ?", (edge_id,))
        return _row_to_edge(row) if row else None

    def get_by_uid(self, edge_uid: str) -> Edge | None:
        row = fetch_one(self.connection, "SELECT * FROM edges WHERE edge_uid = ?", (edge_uid,))
        return _row_to_edge(row) if row else None

    def find_active_relation(self, source_node_id: int, target_node_id: int, edge_type: str) -> Edge | None:
        row = fetch_one(
            self.connection,
            """
            SELECT *
            FROM edges
            WHERE source_node_id = ?
              AND target_node_id = ?
              AND edge_type = ?
              AND is_active = 1
            LIMIT 1
            """,
            (source_node_id, target_node_id, edge_type),
        )
        return _row_to_edge(row) if row else None

    def list_outgoing(
        self,
        source_node_id: int,
        *,
        edge_types: Sequence[str] | None = None,
        active_only: bool = True,
        limit: int | None = None,
    ) -> Sequence[Edge]:
        clauses = ["source_node_id = ?"]
        params: list[object] = [source_node_id]
        if edge_types:
            clauses.append(f"edge_type IN ({placeholders(edge_types)})")
            params.extend(edge_types)
        if active_only:
            clauses.append("is_active = 1")
        sql = f"SELECT * FROM edges WHERE {' AND '.join(clauses)} ORDER BY trust_score DESC, edge_weight DESC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = fetch_all(self.connection, sql, params)
        return [_row_to_edge(row) for row in rows]

    def list_incoming(
        self,
        target_node_id: int,
        *,
        edge_types: Sequence[str] | None = None,
        active_only: bool = True,
        limit: int | None = None,
    ) -> Sequence[Edge]:
        clauses = ["target_node_id = ?"]
        params: list[object] = [target_node_id]
        if edge_types:
            clauses.append(f"edge_type IN ({placeholders(edge_types)})")
            params.extend(edge_types)
        if active_only:
            clauses.append("is_active = 1")
        sql = f"SELECT * FROM edges WHERE {' AND '.join(clauses)} ORDER BY trust_score DESC, edge_weight DESC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = fetch_all(self.connection, sql, params)
        return [_row_to_edge(row) for row in rows]

    def list_edges_for_nodes(self, node_ids: Sequence[int], *, active_only: bool = True) -> Sequence[Edge]:
        if not node_ids:
            return []
        clauses = [
            f"(source_node_id IN ({placeholders(node_ids)}) OR target_node_id IN ({placeholders(node_ids)}))"
        ]
        params: list[object] = list(node_ids) + list(node_ids)
        if active_only:
            clauses.append("is_active = 1")
        rows = fetch_all(
            self.connection,
            f"SELECT * FROM edges WHERE {' AND '.join(clauses)} ORDER BY trust_score DESC, id ASC",
            params,
        )
        return [_row_to_edge(row) for row in rows]

    def bump_support(self, edge_id: int, *, delta: int = 1, trust_delta: float = 0.0) -> None:
        self.connection.execute(
            """
            UPDATE edges
            SET support_count = support_count + ?,
                trust_score = trust_score + ?,
                last_supported_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (delta, trust_delta, edge_id),
        )

    def bump_conflict(
        self,
        edge_id: int,
        *,
        delta: int = 1,
        pressure_delta: float = 1.0,
        trust_delta: float = 0.0,
    ) -> None:
        self.connection.execute(
            """
            UPDATE edges
            SET conflict_count = conflict_count + ?,
                contradiction_pressure = contradiction_pressure + ?,
                trust_score = trust_score + ?,
                last_conflicted_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (delta, pressure_delta, trust_delta, edge_id),
        )

    def set_revision_candidate(self, edge_id: int, *, flag: bool) -> None:
        self.connection.execute(
            "UPDATE edges SET revision_candidate_flag = ? WHERE id = ?",
            (int(flag), edge_id),
        )

    def update_relation_detail(self, edge_id: int, relation_detail: dict) -> None:
        self.connection.execute(
            "UPDATE edges SET relation_detail_json = ? WHERE id = ?",
            (dumps_json(relation_detail), edge_id),
        )

    def update_scores(
        self,
        edge_id: int,
        *,
        edge_weight: float | None = None,
        trust_score: float | None = None,
        contradiction_pressure: float | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[object] = []
        if edge_weight is not None:
            updates.append("edge_weight = ?")
            params.append(edge_weight)
        if trust_score is not None:
            updates.append("trust_score = ?")
            params.append(trust_score)
        if contradiction_pressure is not None:
            updates.append("contradiction_pressure = ?")
            params.append(contradiction_pressure)
        if not updates:
            return
        params.append(edge_id)
        self.connection.execute(f"UPDATE edges SET {', '.join(updates)} WHERE id = ?", params)

    def update_counters(
        self,
        edge_id: int,
        *,
        support_count: int | None = None,
        conflict_count: int | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[object] = []
        if support_count is not None:
            updates.append("support_count = ?")
            params.append(support_count)
        if conflict_count is not None:
            updates.append("conflict_count = ?")
            params.append(conflict_count)
        if not updates:
            return
        params.append(edge_id)
        self.connection.execute(f"UPDATE edges SET {', '.join(updates)} WHERE id = ?", params)

    def reassign(
        self,
        edge_id: int,
        *,
        source_node_id: int | None = None,
        target_node_id: int | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[object] = []
        if source_node_id is not None:
            updates.append("source_node_id = ?")
            params.append(source_node_id)
        if target_node_id is not None:
            updates.append("target_node_id = ?")
            params.append(target_node_id)
        if not updates:
            return
        params.append(edge_id)
        self.connection.execute(f"UPDATE edges SET {', '.join(updates)} WHERE id = ?", params)

    def list_revision_candidates(
        self,
        *,
        min_contradiction_pressure: float = 0.0,
        limit: int = 100,
    ) -> Sequence[Edge]:
        rows = fetch_all(
            self.connection,
            """
            SELECT *
            FROM edges
            WHERE revision_candidate_flag = 1
              AND contradiction_pressure >= ?
              AND is_active = 1
            ORDER BY contradiction_pressure DESC, trust_score ASC, id ASC
            LIMIT ?
            """,
            (min_contradiction_pressure, limit),
        )
        return [_row_to_edge(row) for row in rows]

    def deactivate(self, edge_id: int) -> None:
        self.connection.execute("UPDATE edges SET is_active = 0 WHERE id = ?", (edge_id,))


def _row_to_edge(row: sqlite3.Row) -> Edge:
    return Edge(
        id=int(row["id"]),
        edge_uid=str(row["edge_uid"]),
        source_node_id=int(row["source_node_id"]),
        target_node_id=int(row["target_node_id"]),
        edge_type=str(row["edge_type"]),
        relation_detail=loads_json(row["relation_detail_json"], default={}),
        edge_weight=float(row["edge_weight"]),
        trust_score=float(row["trust_score"]),
        support_count=int(row["support_count"]),
        conflict_count=int(row["conflict_count"]),
        contradiction_pressure=float(row["contradiction_pressure"]),
        revision_candidate_flag=as_bool(row["revision_candidate_flag"]),
        created_from_event_id=row["created_from_event_id"],
        last_supported_at=row["last_supported_at"],
        last_conflicted_at=row["last_conflicted_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        is_active=as_bool(row["is_active"]),
    )
