from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from core.entities.node import Node
from storage.repositories.node_repository import NodeRepository
from storage.sqlite.common import as_bool, dumps_json, fetch_all, fetch_one, loads_json, placeholders


class SqliteNodeRepository(NodeRepository):
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def ping(self) -> None:
        self.connection.execute("SELECT 1").fetchone()

    def add(self, node: Node) -> Node:
        cursor = self.connection.execute(
            """
            INSERT INTO nodes (
                node_uid, address_hash, node_kind, raw_value, normalized_value,
                payload_json, trust_score, stability_score, revision_state,
                created_from_event_id, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.node_uid,
                node.address_hash,
                "node",
                node.raw_value,
                node.normalized_value,
                dumps_json(node.payload),
                node.trust_score,
                node.stability_score,
                node.revision_state,
                node.created_from_event_id,
                int(node.is_active),
            ),
        )
        return self.get_by_id(int(cursor.lastrowid)) or node

    def get_by_id(self, node_id: int) -> Node | None:
        row = fetch_one(self.connection, "SELECT * FROM nodes WHERE id = ?", (node_id,))
        return _row_to_node(row) if row else None

    def get_by_uid(self, node_uid: str) -> Node | None:
        row = fetch_one(self.connection, "SELECT * FROM nodes WHERE node_uid = ?", (node_uid,))
        return _row_to_node(row) if row else None

    def get_by_address_hash(self, address_hash: str) -> Node | None:
        row = fetch_one(self.connection, "SELECT * FROM nodes WHERE address_hash = ?", (address_hash,))
        return _row_to_node(row) if row else None

    def list_by_address_hashes(self, address_hashes: Sequence[str]) -> Sequence[Node]:
        if not address_hashes:
            return []
        rows = fetch_all(
            self.connection,
            f"SELECT * FROM nodes WHERE address_hash IN ({placeholders(address_hashes)})",
            list(address_hashes),
        )
        by_hash = {str(row["address_hash"]): _row_to_node(row) for row in rows}
        return [by_hash[address_hash] for address_hash in address_hashes if address_hash in by_hash]

    def list_by_ids(self, node_ids: Sequence[int]) -> Sequence[Node]:
        if not node_ids:
            return []
        rows = fetch_all(
            self.connection,
            f"SELECT * FROM nodes WHERE id IN ({placeholders(node_ids)})",
            list(node_ids),
        )
        by_id = {int(row["id"]): _row_to_node(row) for row in rows}
        return [by_id[node_id] for node_id in node_ids if node_id in by_id]

    def search_by_normalized_value(
        self,
        normalized_value: str,
        *,
        active_only: bool = True,
        limit: int = 20,
    ) -> Sequence[Node]:
        clauses = ["normalized_value = ?"]
        params: list[object] = [normalized_value]
        if active_only:
            clauses.append("is_active = 1")
        params.append(limit)
        rows = fetch_all(
            self.connection,
            f"""
            SELECT *
            FROM nodes
            WHERE {' AND '.join(clauses)}
            ORDER BY trust_score DESC, stability_score DESC, id ASC
            LIMIT ?
            """,
            params,
        )
        return [_row_to_node(row) for row in rows]

    def update_payload(self, node_id: int, payload: dict) -> None:
        self.connection.execute(
            "UPDATE nodes SET payload_json = ? WHERE id = ?",
            (dumps_json(payload), node_id),
        )

    def update_scores(
        self,
        node_id: int,
        *,
        trust_score: float | None = None,
        stability_score: float | None = None,
        revision_state: str | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[object] = []
        if trust_score is not None:
            updates.append("trust_score = ?")
            params.append(trust_score)
        if stability_score is not None:
            updates.append("stability_score = ?")
            params.append(stability_score)
        if revision_state is not None:
            updates.append("revision_state = ?")
            params.append(revision_state)
        if not updates:
            return
        params.append(node_id)
        self.connection.execute(f"UPDATE nodes SET {', '.join(updates)} WHERE id = ?", params)

    def deactivate(self, node_id: int, *, revision_state: str = "deprecated") -> None:
        self.connection.execute(
            "UPDATE nodes SET is_active = 0, revision_state = ? WHERE id = ?",
            (revision_state, node_id),
        )


def _row_to_node(row: sqlite3.Row) -> Node:
    return Node(
        id=int(row["id"]),
        node_uid=str(row["node_uid"]),
        address_hash=str(row["address_hash"]),
        node_kind="node",
        raw_value=str(row["raw_value"]),
        normalized_value=row["normalized_value"],
        payload=loads_json(row["payload_json"], default={}),
        trust_score=float(row["trust_score"]),
        stability_score=float(row["stability_score"]),
        revision_state=str(row["revision_state"]),
        created_from_event_id=row["created_from_event_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        is_active=as_bool(row["is_active"]),
    )
