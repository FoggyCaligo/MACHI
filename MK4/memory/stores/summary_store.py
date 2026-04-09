import json
import uuid

from memory.db import connection_context, utc_now
from memory.stores.topic_store import TopicStore


class SummaryStore:
    def __init__(self) -> None:
        self.topic_store = TopicStore()

    def _resolve_topic_id(self, *, topic: str | None = None, topic_id: str | None = None, create_if_missing: bool = False) -> str | None:
        if topic_id:
            return topic_id
        if not topic or str(topic).strip().lower() == "general":
            return None
        if create_if_missing:
            return self.topic_store.ensure_topic(topic, source="summary_store", confidence=0.6)
        return self.topic_store.find_exact_topic_id(topic)

    def _base_select(self) -> str:
        return (
            "SELECT s.*, t.name AS topic_name, t.summary AS topic_summary "
            "FROM summaries s LEFT JOIN topics t ON s.topic_id = t.id"
        )

    def upsert_topic_summary(self, topic: str, content: str, source_episode_ids: list[str], topic_id: str | None = None):
        now = utc_now()
        encoded = json.dumps(source_episode_ids, ensure_ascii=False)
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=True)
        with connection_context() as conn:
            if resolved_topic_id:
                existing = conn.execute(
                    "SELECT id FROM summaries WHERE topic_id = ? LIMIT 1",
                    (resolved_topic_id,),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id FROM summaries WHERE topic_id IS NULL LIMIT 1"
                ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE summaries SET content = ?, source_episode_ids = ?, updated_at = ?, topic_id = ? WHERE id = ?",
                    (content, encoded, now, resolved_topic_id, existing['id']),
                )
                return existing['id']
            summary_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO summaries (id, topic_id, content, source_episode_ids, updated_at) VALUES (?, ?, ?, ?, ?)",
                (summary_id, resolved_topic_id, content, encoded, now),
            )
            return summary_id

    def get_by_topic(self, topic: str | None = None, topic_id: str | None = None):
        resolved_topic_id = self._resolve_topic_id(topic=topic, topic_id=topic_id, create_if_missing=False)
        with connection_context() as conn:
            if resolved_topic_id:
                row = conn.execute(f"{self._base_select()} WHERE s.topic_id = ? LIMIT 1", (resolved_topic_id,)).fetchone()
            else:
                row = conn.execute(f"{self._base_select()} WHERE s.topic_id IS NULL LIMIT 1").fetchone()
            return dict(row) if row else None

    def search(self, query: str, limit: int = 5):
        pattern = f"%{query}%"
        with connection_context() as conn:
            rows = conn.execute(
                f"{self._base_select()} WHERE COALESCE(t.summary, '') LIKE ? OR COALESCE(t.name, '') LIKE ? OR s.content LIKE ? ORDER BY s.updated_at DESC LIMIT ?",
                (pattern, pattern, pattern, limit),
            ).fetchall()
            return [dict(r) for r in rows]
