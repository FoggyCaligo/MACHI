import uuid
from typing import Any

from memory.db import connection_context, utc_now
from memory.stores.topic_store import TopicStore


class CorrectionStore:
    def __init__(self) -> None:
        self.topic_store = TopicStore()

    def _resolve_topic_id(self, *, topic: str | None = None, topic_id: str | None = None, create_if_missing: bool = False) -> str | None:
        if topic_id:
            return topic_id
        if not topic or str(topic).strip().lower() == "general":
            return None
        if create_if_missing:
            return self.topic_store.ensure_topic(topic, source="correction_store", confidence=0.8)
        return self.topic_store.find_exact_topic_id(topic)

    def _build_topic_clause(self, resolved_topic_id: str | None) -> tuple[str, tuple]:
        if resolved_topic_id:
            return "c.topic_id = ?", (resolved_topic_id,)
        return "c.topic_id IS NULL", ()

    def _base_select(self) -> str:
        return (
            "SELECT c.*, t.name AS topic_name, t.summary AS topic_summary "
            "FROM corrections c LEFT JOIN topics t ON c.topic_id = t.id"
        )

    def add_correction(self, topic: str, content: str, reason: str, source: str = "user_explicit", supersedes_profile_id: str | None = None, supersedes_correction_id: str | None = None, topic_id: str | None = None):
        correction_id = str(uuid.uuid4())
        now = utc_now()
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=True)
        with connection_context() as conn:
            conn.execute(
                """
                INSERT INTO corrections (
                    id, topic_id, content, reason, source, confidence,
                    supersedes_profile_id, supersedes_correction_id,
                    applied_to_profile, created_at, status
                ) VALUES (?, ?, ?, ?, ?, 1.0, ?, ?, 0, ?, 'active')
                """,
                (correction_id, resolved_topic_id, content, reason, source, supersedes_profile_id, supersedes_correction_id, now),
            )
        self.trim_active_queue(keep=5)
        return correction_id

    def list_active(self, limit: int = 5):
        with connection_context() as conn:
            rows = conn.execute(
                f"{self._base_select()} WHERE c.status = 'active' ORDER BY c.created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_active_by_topic(self, topic: str | None = None, topic_id: str | None = None, limit: int = 5):
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=False)
        clause, values = self._build_topic_clause(resolved_topic_id)
        with connection_context() as conn:
            rows = conn.execute(
                f"{self._base_select()} WHERE {clause} AND c.status = 'active' ORDER BY c.created_at DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 5):
        pattern = f"%{query}%"
        with connection_context() as conn:
            rows = conn.execute(
                f"{self._base_select()} WHERE c.status IN ('active', 'applied') AND (COALESCE(t.summary, '') LIKE ? OR COALESCE(t.name, '') LIKE ? OR c.content LIKE ?) ORDER BY c.created_at DESC LIMIT ?",
                (pattern, pattern, pattern, limit),
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
