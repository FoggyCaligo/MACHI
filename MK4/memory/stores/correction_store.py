import uuid
from typing import Any

from memory.db import connection_context, utc_now


class CorrectionStore:
    def add_correction(self, topic: str, content: str, reason: str, source: str = "user_explicit", supersedes_profile_id: str | None = None, supersedes_correction_id: str | None = None):
        correction_id = str(uuid.uuid4())
        now = utc_now()
        with connection_context() as conn:
            conn.execute(
                """
                INSERT INTO corrections (
                    id, topic, content, reason, source, confidence,
                    supersedes_profile_id, supersedes_correction_id,
                    applied_to_profile, created_at, status
                ) VALUES (?, ?, ?, ?, ?, 1.0, ?, ?, 0, ?, 'active')
                """,
                (correction_id, topic, content, reason, source, supersedes_profile_id, supersedes_correction_id, now),
            )
        self.trim_active_queue(keep=5)
        return correction_id

    def list_active(self, limit: int = 5):
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM corrections WHERE status = 'active' ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_active_by_topic(self, topic: str, limit: int = 5):
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM corrections WHERE topic = ? AND status = 'active' ORDER BY created_at DESC LIMIT ?",
                (topic, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 5):
        pattern = f"%{query}%"
        with connection_context() as conn:
            rows = conn.execute(
                """
                SELECT * FROM corrections
                WHERE status IN ('active', 'applied') AND (topic LIKE ? OR content LIKE ?)
                ORDER BY created_at DESC LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_applied(self, correction_id: str):
        with connection_context() as conn:
            conn.execute(
                "UPDATE corrections SET applied_to_profile = 1, status = 'applied' WHERE id = ?",
                (correction_id,),
            )

    def trim_active_queue(self, keep: int = 5):
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM corrections WHERE status = 'active' ORDER BY created_at DESC"
            ).fetchall()
            active = [dict(r) for r in rows]
            for correction in active[keep:]:
                if correction['applied_to_profile']:
                    conn.execute("DELETE FROM corrections WHERE id = ?", (correction['id'],))
                else:
                    conn.execute("UPDATE corrections SET status = 'removed' WHERE id = ?", (correction['id'],))
