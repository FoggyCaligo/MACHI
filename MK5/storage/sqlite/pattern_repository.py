from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from core.entities.subgraph_pattern import SubgraphPattern
from storage.repositories.pattern_repository import PatternRepository
from storage.sqlite.common import dumps_json, fetch_all, fetch_one, loads_json, placeholders


class SqlitePatternRepository(PatternRepository):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ping(self) -> None:
        self.connection.execute("SELECT 1").fetchone()

    def add(self, pattern: SubgraphPattern) -> SubgraphPattern:
        cursor = self.connection.execute(
            """
            INSERT INTO subgraph_patterns (
                pattern_uid, pattern_type, node_ids_json, edge_ids_json,
                topology_hash, cardinality, edge_count,
                pattern_trust, backing_evidence_count, conflict_count,
                conflict_pressure, is_active,
                payload_json, created_from_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pattern.pattern_uid,
                pattern.pattern_type,
                dumps_json(pattern.node_ids),
                dumps_json(pattern.edge_ids),
                pattern.topology_hash,
                pattern.cardinality,
                pattern.edge_count,
                pattern.pattern_trust,
                pattern.backing_evidence_count,
                pattern.conflict_count,
                pattern.conflict_pressure,
                int(pattern.is_active),
                dumps_json(pattern.payload),
                pattern.created_from_event_id,
            ),
        )
        return self.get_by_id(int(cursor.lastrowid)) or pattern

    def get_by_id(self, pattern_id: int) -> SubgraphPattern | None:
        row = fetch_one(self.connection, "SELECT * FROM subgraph_patterns WHERE id = ?", (pattern_id,))
        return _row_to_pattern(row) if row else None

    def get_by_uid(self, pattern_uid: str) -> SubgraphPattern | None:
        row = fetch_one(self.connection, "SELECT * FROM subgraph_patterns WHERE pattern_uid = ?", (pattern_uid,))
        return _row_to_pattern(row) if row else None

    def get_by_topology_hash(self, topology_hash: str) -> SubgraphPattern | None:
        row = fetch_one(
            self.connection,
            "SELECT * FROM subgraph_patterns WHERE topology_hash = ? AND is_active = 1 LIMIT 1",
            (topology_hash,),
        )
        return _row_to_pattern(row) if row else None

    def list_by_node_ids(
        self,
        node_ids: Sequence[int],
        *,
        active_only: bool = True,
    ) -> Sequence[SubgraphPattern]:
        """Return all patterns that contain any of the given nodes.
        
        Uses JSON array containment checks.
        """
        if not node_ids:
            return []
        
        clauses = []
        for node_id in node_ids:
            # SQLite JSON check: json_extract(json_array, '$[*]') contains value
            clauses.append(f"json_array_length(subgraph_patterns.node_ids_json) > 0")
        
        where_clause = f"is_active = 1" if active_only else "1=1"
        
        # Simpler approach: fetch all and filter in Python
        # (SQLite JSON array containment is complex in older versions)
        sql = f"""
            SELECT * FROM subgraph_patterns
            WHERE {where_clause}
            ORDER BY pattern_trust DESC, backing_evidence_count DESC, id ASC
        """
        rows = fetch_all(self.connection, sql, [])
        
        result = []
        for row in rows:
            pattern = _row_to_pattern(row)
            if pattern and any(nid in pattern.node_ids for nid in node_ids):
                result.append(pattern)
        return result

    def list_active_patterns(
        self,
        *,
        pattern_types: Sequence[str] | None = None,
        min_trust: float = 0.0,
        limit: int | None = None,
    ) -> Sequence[SubgraphPattern]:
        clauses = ["is_active = 1", "pattern_trust >= ?"]
        params: list[object] = [min_trust]
        
        if pattern_types:
            clauses.append(f"pattern_type IN ({placeholders(pattern_types)})")
            params.extend(pattern_types)
        
        sql = f"""
            SELECT * FROM subgraph_patterns
            WHERE {' AND '.join(clauses)}
            ORDER BY pattern_trust DESC, backing_evidence_count DESC, id ASC
        """
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        
        rows = fetch_all(self.connection, sql, params)
        return [_row_to_pattern(row) for row in rows]

    def update_payload(self, pattern_id: int, payload: dict) -> None:
        self.connection.execute(
            "UPDATE subgraph_patterns SET payload_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (dumps_json(payload), pattern_id),
        )

    def update_trust_and_pressure(
        self,
        pattern_id: int,
        *,
        pattern_trust: float | None = None,
        conflict_pressure: float | None = None,
        backing_evidence_count: int | None = None,
        conflict_count: int | None = None,
    ) -> None:
        updates = ["updated_at = CURRENT_TIMESTAMP"]
        params: list[object] = []
        
        if pattern_trust is not None:
            updates.append("pattern_trust = ?")
            params.append(pattern_trust)
        if conflict_pressure is not None:
            updates.append("conflict_pressure = ?")
            params.append(conflict_pressure)
        if backing_evidence_count is not None:
            updates.append("backing_evidence_count = ?")
            params.append(backing_evidence_count)
        if conflict_count is not None:
            updates.append("conflict_count = ?")
            params.append(conflict_count)
        
        if len(updates) == 1:  # Only timestamp
            return
        
        params.append(pattern_id)
        sql = f"UPDATE subgraph_patterns SET {', '.join(updates)} WHERE id = ?"
        self.connection.execute(sql, params)

    def bump_backing_evidence(
        self,
        pattern_id: int,
        *,
        delta: int = 1,
        trust_delta: float = 0.0,
    ) -> None:
        # Fetch current value first
        pattern = self.get_by_id(pattern_id)
        if pattern is None:
            return
        
        new_trust = max(0.0, min(1.0, pattern.pattern_trust + trust_delta))
        self.connection.execute(
            """
            UPDATE subgraph_patterns
            SET backing_evidence_count = backing_evidence_count + ?,
                pattern_trust = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (delta, new_trust, pattern_id),
        )

    def bump_conflict(
        self,
        pattern_id: int,
        *,
        delta: int = 1,
        pressure_delta: float = 1.0,
        trust_delta: float = 0.0,
    ) -> None:
        # Fetch current value first
        pattern = self.get_by_id(pattern_id)
        if pattern is None:
            return
        
        new_trust = max(0.0, min(1.0, pattern.pattern_trust + trust_delta))
        self.connection.execute(
            """
            UPDATE subgraph_patterns
            SET conflict_count = conflict_count + ?,
                conflict_pressure = conflict_pressure + ?,
                pattern_trust = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (delta, pressure_delta, new_trust, pattern_id),
        )

    def set_superseded(self, pattern_id: int, *, superseded_by: str) -> None:
        self.connection.execute(
            "UPDATE subgraph_patterns SET superseded_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (superseded_by, pattern_id),
        )

    def deactivate(self, pattern_id: int) -> None:
        self.connection.execute(
            "UPDATE subgraph_patterns SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (pattern_id,),
        )


def _row_to_pattern(row: tuple) -> SubgraphPattern:
    """Convert a database row to a SubgraphPattern entity."""
    return SubgraphPattern(
        id=row[0],
        pattern_uid=row[1],
        pattern_type=row[2],
        node_ids=loads_json(row[3], default=[]) if row[3] else [],
        edge_ids=loads_json(row[4], default=[]) if row[4] else [],
        topology_hash=row[5],
        cardinality=row[6],
        edge_count=row[7],
        pattern_trust=row[8],
        backing_evidence_count=row[9],
        conflict_count=row[10],
        conflict_pressure=row[11],
        is_active=bool(row[12]),
        superseded_by=row[13],
        payload=loads_json(row[14], default={}) if row[14] else {},
        created_from_event_id=row[15],
        created_at=row[16],
        updated_at=row[17],
    )
