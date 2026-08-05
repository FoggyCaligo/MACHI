from __future__ import annotations

import json
import uuid
from typing import Any

from memory.db import connection_context, utc_now
from tools.text_embedding import cosine_similarity, embed_text


class TopicStore:
    def _decode_embedding(self, raw: str | None) -> list[float]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        result: list[float] = []
        for item in data:
            try:
                result.append(float(item))
            except (TypeError, ValueError):
                return []
        return result

    def _encode_embedding(self, embedding: list[float] | None) -> str:
        return json.dumps(embedding or [], ensure_ascii=False)

    def _normalize_topic_text(self, text: str | None) -> str:
        normalized = " ".join((text or "").strip().split())
        return normalized[:180].strip()

    def _row_to_topic(self, row: Any) -> dict[str, Any]:
        topic = dict(row)
        topic["embedding"] = self._decode_embedding(topic.get("embedding_json"))
        return topic

    def create_topic(
        self,
        *,
        name: str,
        summary: str | None = None,
        source: str,
        confidence: float = 0.0,
        embedding: list[float] | None = None,
    ) -> str:
        now = utc_now()
        topic_id = str(uuid.uuid4())
        normalized_name = self._normalize_topic_text(name)
        normalized_summary = self._normalize_topic_text(summary or normalized_name)
        resolved_embedding = embedding or embed_text(normalized_summary, kind="passage")

        with connection_context() as conn:
            conn.execute(
                """
                INSERT INTO topics (
                    id, name, summary, embedding_json, confidence, source, status,
                    usage_count, last_used_at, created_at, updated_at, merged_into_topic_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?, NULL)
                """,
                (
                    topic_id,
                    normalized_name,
                    normalized_summary,
                    self._encode_embedding(resolved_embedding),
                    float(confidence),
                    source,
                    now,
                    now,
                    now,
                ),
            )
        return topic_id

    def get_topic(self, topic_id: str) -> dict[str, Any] | None:
        with connection_context() as conn:
            row = conn.execute("SELECT * FROM topics WHERE id = ? LIMIT 1", (topic_id,)).fetchone()
            return self._row_to_topic(row) if row else None

    def find_exact_topic_id(self, text: str | None) -> str | None:
        normalized = self._normalize_topic_text(text)
        if not normalized or normalized.lower() == "general":
            return None
        with connection_context() as conn:
            row = conn.execute(
                """
                SELECT id FROM topics
                WHERE LOWER(summary) = LOWER(?) OR LOWER(name) = LOWER(?)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (normalized, normalized),
            ).fetchone()
            return str(row[0]).strip() if row else None

    def ensure_topic(
        self,
        text: str | None,
        *,
        source: str,
        confidence: float = 0.0,
    ) -> str | None:
        normalized = self._normalize_topic_text(text)
        if not normalized or normalized.lower() == "general":
            return None
        existing_id = self.find_exact_topic_id(normalized)
        if existing_id:
            return existing_id
        return self.create_topic(
            name=normalized,
            summary=normalized,
            source=source,
            confidence=confidence,
        )

    def get_topic_summary(self, topic_id: str | None) -> str:
        if not topic_id:
            return "general"
        topic = self.get_topic(topic_id)
        if not topic:
            return "general"
        return str(topic.get("summary") or topic.get("name") or "general").strip() or "general"

    def list_active_topics(self, limit: int = 100) -> list[dict[str, Any]]:
        with connection_context() as conn:
            rows = conn.execute(
                """
                SELECT * FROM topics
                WHERE status = 'active'
                ORDER BY COALESCE(last_used_at, updated_at) DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_topic(row) for row in rows]

    def mark_used(self, topic_id: str) -> None:
        now = utc_now()
        with connection_context() as conn:
            conn.execute(
                """
                UPDATE topics
                SET usage_count = usage_count + 1,
                    last_used_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, topic_id),
            )

    def update_topic(
        self,
        topic_id: str,
        *,
        name: str | None = None,
        summary: str | None = None,
        confidence: float | None = None,
        embedding: list[float] | None = None,
        status: str | None = None,
        merged_into_topic_id: str | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []

        if name is not None:
            fields.append("name = ?")
            values.append(self._normalize_topic_text(name))
        if summary is not None:
            normalized_summary = self._normalize_topic_text(summary)
            fields.append("summary = ?")
            values.append(normalized_summary)
            if embedding is None:
                embedding = embed_text(normalized_summary, kind="passage")
        if confidence is not None:
            fields.append("confidence = ?")
            values.append(float(confidence))
        if embedding is not None:
            fields.append("embedding_json = ?")
            values.append(self._encode_embedding(embedding))
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if merged_into_topic_id is not None:
            fields.append("merged_into_topic_id = ?")
            values.append(merged_into_topic_id)

        if not fields:
            return

        fields.append("updated_at = ?")
        values.append(utc_now())
        values.append(topic_id)

        with connection_context() as conn:
            conn.execute(
                f"UPDATE topics SET {', '.join(fields)} WHERE id = ?",
                tuple(values),
            )

    def find_similar_topics(
        self,
        *,
        text: str,
        limit: int = 5,
        min_similarity: float = 0.0,
        exclude_topic_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query_embedding = embed_text(text, kind="query")
        if not query_embedding:
            return []

        topics = self.list_active_topics(limit=500)
        scored: list[dict[str, Any]] = []
        for topic in topics:
            if exclude_topic_id and topic.get("id") == exclude_topic_id:
                continue
            similarity = cosine_similarity(query_embedding, topic.get("embedding") or [])
            if similarity < min_similarity:
                continue
            topic_with_score = dict(topic)
            topic_with_score["similarity"] = similarity
            scored.append(topic_with_score)

        scored.sort(key=lambda item: item.get("similarity", 0.0), reverse=True)
        return scored[:limit]
