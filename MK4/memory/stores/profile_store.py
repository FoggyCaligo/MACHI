import uuid
from typing import Any

from memory.db import connection_context, utc_now
from memory.stores.topic_store import TopicStore


class ProfileStore:
    def __init__(self) -> None:
        self.topic_store = TopicStore()

    def _resolve_topic_id(self, *, topic: str | None = None, topic_id: str | None = None, create_if_missing: bool = False) -> str | None:
        if topic_id:
            return topic_id
        if not topic or str(topic).strip().lower() == "general":
            return None
        if create_if_missing:
            return self.topic_store.ensure_topic(topic, source="profile_store", confidence=0.7)
        return self.topic_store.find_exact_topic_id(topic)

    def _build_topic_clause(self, resolved_topic_id: str | None) -> tuple[str, tuple]:
        if resolved_topic_id:
            return "p.topic_id = ?", (resolved_topic_id,)
        return "p.topic_id IS NULL", ()

    def _base_select(self) -> str:
        return (
            "SELECT p.*, t.name AS topic_name, t.summary AS topic_summary "
            "FROM profiles p LEFT JOIN topics t ON p.topic_id = t.id"
        )

    def get_active_by_topic(self, topic: str | None = None, topic_id: str | None = None) -> dict[str, Any] | None:
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=False)
        clause, values = self._build_topic_clause(resolved_topic_id)
        with connection_context() as conn:
            row = conn.execute(
                f"{self._base_select()} WHERE {clause} AND p.status = 'active' ORDER BY p.updated_at DESC LIMIT 1",
                values,
            ).fetchone()
            return dict(row) if row else None


    def get_profile_by_id(self, profile_id: str) -> dict[str, Any] | None:
        if not profile_id:
            return None
        with connection_context() as conn:
            row = conn.execute(
                f"{self._base_select()} WHERE p.id = ? LIMIT 1",
                (profile_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_active_profiles(self, exclude_general: bool = False) -> list[dict[str, Any]]:
        query = f"{self._base_select()} WHERE p.status = 'active'"
        if exclude_general:
            query += " AND p.topic_id IS NOT NULL"
        query += " ORDER BY p.updated_at DESC"
        with connection_context() as conn:
            rows = conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    def get_recent_history(self, topic: str | None = None, topic_id: str | None = None, limit: int = 2) -> list[dict[str, Any]]:
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=False)
        clause, values = self._build_topic_clause(resolved_topic_id)
        with connection_context() as conn:
            rows = conn.execute(
                f"{self._base_select()} WHERE {clause} AND p.status = 'superseded' ORDER BY p.updated_at DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 5, include_general: bool = True) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        sql = (
            f"{self._base_select()} WHERE p.status = 'active' "
            "AND (COALESCE(t.summary, '') LIKE ? OR COALESCE(t.name, '') LIKE ? OR p.content LIKE ?)"
        )
        params = [pattern, pattern, pattern]
        if not include_general:
            sql += " AND p.topic_id IS NOT NULL"
        sql += " ORDER BY p.updated_at DESC LIMIT ?"
        params.append(limit)
        with connection_context() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(r) for r in rows]

    def insert_profile(self, topic: str, content: str, source: str, confidence: float = 1.0, topic_id: str | None = None):
        now = utc_now()
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=True)
        clause, values = self._build_topic_clause(resolved_topic_id)
        with connection_context() as conn:
            active = conn.execute(
                f"SELECT * FROM profiles p WHERE {clause} AND p.status = 'active' ORDER BY p.updated_at DESC LIMIT 1",
                values,
            ).fetchone()
            version_no = 1
            if active:
                version_no = int(active['version_no']) + 1
                conn.execute(
                    "UPDATE profiles SET status = 'superseded', updated_at = ? WHERE id = ?",
                    (now, active['id']),
                )
            new_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO profiles (id, topic_id, content, confidence, source, version_no, created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (new_id, resolved_topic_id, content, confidence, source, version_no, now, now),
            )
        self.trim_history(topic=topic, topic_id=resolved_topic_id, keep_superseded=2)
        return new_id

    def trim_history(self, topic: str | None = None, topic_id: str | None = None, keep_superseded: int = 2):
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=False)
        clause, values = self._build_topic_clause(resolved_topic_id)
        with connection_context() as conn:
            rows = conn.execute(
                f"SELECT p.id FROM profiles p WHERE {clause} AND p.status = 'superseded' ORDER BY p.updated_at DESC",
                values,
            ).fetchall()
            for row in rows[keep_superseded:]:
                conn.execute("DELETE FROM profiles WHERE id = ?", (row['id'],))
