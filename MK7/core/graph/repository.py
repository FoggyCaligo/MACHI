from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ... import config
from .models import GraphEdge, GraphNode


class GraphRepository:
    """SQLite-backed graph repository for MK7."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path == ":memory:":
            self._conn = sqlite3.connect(":memory:")
        else:
            resolved_path = Path(db_path or config.DB_PATH).resolve()
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(resolved_path))
        self._conn.row_factory = sqlite3.Row
        self._initialize_schema()

    def get_node(self, node_id: str) -> GraphNode | None:
        row = self._conn.execute(
            """
            SELECT node_id, labels_json, node_type, payload_json
            FROM graph_nodes
            WHERE node_id = ?
            """,
            (node_id,),
        ).fetchone()
        return self._node_from_row(row) if row is not None else None

    def upsert_node(self, node: GraphNode) -> None:
        self._conn.execute(
            """
            INSERT INTO graph_nodes (node_id, labels_json, node_type, payload_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                labels_json = excluded.labels_json,
                node_type = excluded.node_type,
                payload_json = excluded.payload_json
            """,
            (
                node.node_id,
                json.dumps(node.labels, ensure_ascii=False),
                node.node_type,
                json.dumps(node.payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        self._conn.commit()

    def add_edge(self, edge: GraphEdge) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO graph_edges (source_id, target_id, relation, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                edge.source_id,
                edge.target_id,
                edge.relation,
                json.dumps(edge.payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        self._conn.commit()

    def neighbors(self, node_id: str) -> list[GraphNode]:
        neighbor_ids: set[str] = set()
        rows = self._conn.execute(
            """
            SELECT source_id, target_id
            FROM graph_edges
            WHERE source_id = ? OR target_id = ?
            ORDER BY edge_id ASC
            """,
            (node_id, node_id),
        ).fetchall()
        for row in rows:
            source_id = str(row["source_id"])
            target_id = str(row["target_id"])
            if source_id == node_id:
                neighbor_ids.add(target_id)
            elif target_id == node_id:
                neighbor_ids.add(source_id)
        return [node for nid in sorted(neighbor_ids) if (node := self.get_node(nid)) is not None]

    def all_nodes(self) -> list[GraphNode]:
        rows = self._conn.execute(
            """
            SELECT node_id, labels_json, node_type, payload_json
            FROM graph_nodes
            ORDER BY node_id ASC
            """
        ).fetchall()
        return [self._node_from_row(row) for row in rows]

    def all_edges(self) -> list[GraphEdge]:
        rows = self._conn.execute(
            """
            SELECT source_id, target_id, relation, payload_json
            FROM graph_edges
            ORDER BY edge_id ASC
            """
        ).fetchall()
        return [self._edge_from_row(row) for row in rows]

    def edges_for_node(self, node_id: str) -> list[GraphEdge]:
        rows = self._conn.execute(
            """
            SELECT source_id, target_id, relation, payload_json
            FROM graph_edges
            WHERE source_id = ? OR target_id = ?
            ORDER BY edge_id ASC
            """,
            (node_id, node_id),
        ).fetchall()
        return [self._edge_from_row(row) for row in rows]

    def search_nodes(self, query: str, *, limit: int = 8) -> list[GraphNode]:
        normalized = query.strip().lower()
        if not normalized:
            return []

        scored: list[tuple[int, GraphNode]] = []
        for node in self.all_nodes():
            haystack = " ".join(node.labels).lower()
            if normalized not in haystack:
                continue
            score = 0
            if node.labels and normalized == node.labels[0].lower():
                score += 3
            if normalized in haystack:
                score += 1
            scored.append((score, node))

        scored.sort(key=lambda item: (-item[0], item[1].node_id))
        return [node for _, node in scored[:limit]]

    def close(self) -> None:
        self._conn.close()

    def _initialize_schema(self) -> None:
        self._conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS graph_nodes (
                node_id TEXT PRIMARY KEY,
                labels_json TEXT NOT NULL,
                node_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS graph_edges (
                edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                UNIQUE(source_id, target_id, relation, payload_json)
            );

            CREATE INDEX IF NOT EXISTS idx_graph_edges_source_id ON graph_edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_graph_edges_target_id ON graph_edges(target_id);
            """
        )
        self._conn.commit()

    def _node_from_row(self, row: sqlite3.Row) -> GraphNode:
        return GraphNode(
            node_id=str(row["node_id"]),
            labels=self._decode_json_list(str(row["labels_json"])),
            node_type=str(row["node_type"]),
            payload=self._decode_json_dict(str(row["payload_json"])),
        )

    def _edge_from_row(self, row: sqlite3.Row) -> GraphEdge:
        return GraphEdge(
            source_id=str(row["source_id"]),
            target_id=str(row["target_id"]),
            relation=str(row["relation"]),
            payload=self._decode_json_dict(str(row["payload_json"])),
        )

    def _decode_json_list(self, raw: str) -> list[str]:
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return [str(item) for item in data]

    def _decode_json_dict(self, raw: str) -> dict:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return dict(data)
