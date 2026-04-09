import json
import uuid

from memory.db import connection_context, utc_now


class SummaryStore:
    def upsert_topic_summary(self, topic: str, content: str, source_episode_ids: list[str], topic_id: str | None = None):
        now = utc_now()
        encoded = json.dumps(source_episode_ids, ensure_ascii=False)
        with connection_context() as conn:
            if topic_id:
                existing = conn.execute(
                    "SELECT id FROM summaries WHERE topic_id = ? LIMIT 1",
                    (topic_id,),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id FROM summaries WHERE topic = ? LIMIT 1",
                    (topic,),
                ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE summaries SET content = ?, source_episode_ids = ?, updated_at = ?, topic = ?, topic_id = ? WHERE id = ?",
                    (content, encoded, now, topic, topic_id, existing['id']),
                )
                return existing['id']
            summary_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO summaries (id, topic_id, topic, content, source_episode_ids, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (summary_id, topic_id, topic, content, encoded, now),
            )
            return summary_id

    def get_by_topic(self, topic: str | None = None, topic_id: str | None = None):
        with connection_context() as conn:
            if topic_id:
                row = conn.execute("SELECT * FROM summaries WHERE topic_id = ? LIMIT 1", (topic_id,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM summaries WHERE topic = ? LIMIT 1", (topic,)).fetchone()
            return dict(row) if row else None

    def search(self, query: str, limit: int = 5):
        pattern = f"%{query}%"
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM summaries WHERE topic LIKE ? OR content LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
            return [dict(r) for r in rows]
