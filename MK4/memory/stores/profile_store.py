import uuid
from typing import Any

from memory.db import connection_context, utc_now


class ProfileStore:
    def get_active_by_topic(self, topic: str) -> dict[str, Any] | None:
        with connection_context() as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE topic = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
                (topic,),
            ).fetchone()
            return dict(row) if row else None

    def get_active_profiles(self) -> list[dict[str, Any]]:
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM profiles WHERE status = 'active' ORDER BY topic, updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_history(self, topic: str, limit: int = 2) -> list[dict[str, Any]]:
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM profiles WHERE topic = ? AND status = 'superseded' ORDER BY updated_at DESC LIMIT ?",
                (topic, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        with connection_context() as conn:
            rows = conn.execute(
                """
                SELECT * FROM profiles
                WHERE status = 'active' AND (topic LIKE ? OR content LIKE ?)
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def insert_profile(self, topic: str, content: str, source: str, confidence: float = 1.0):
        now = utc_now()
        with connection_context() as conn:
            active = conn.execute(
                "SELECT * FROM profiles WHERE topic = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 1",
                (topic,),
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
                INSERT INTO profiles (id, topic, content, confidence, source, version_no, created_at, updated_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (new_id, topic, content, confidence, source, version_no, now, now),
            )
        self.trim_history(topic, keep_superseded=2)
        return new_id

    def trim_history(self, topic: str, keep_superseded: int = 2):
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT id FROM profiles WHERE topic = ? AND status = 'superseded' ORDER BY updated_at DESC",
                (topic,),
            ).fetchall()
            ids = [r['id'] for r in rows]
            for old_id in ids[keep_superseded:]:
                conn.execute("DELETE FROM profiles WHERE id = ?", (old_id,))
