import uuid
from typing import Any

from memory.db import connection_context, utc_now
from tools.text_embedding import cosine_similarity, embed_text, embed_texts


class RawMessageStore:
    def add(self, role: str, content: str, episode_id: str | None = None):
        if content is None:
            return None

        content = content.strip()
        if not content:
            return None

        message_id = str(uuid.uuid4())
        with connection_context() as conn:
            conn.execute(
                "INSERT INTO raw_messages (id, role, content, created_at, episode_id) VALUES (?, ?, ?, ?, ?)",
                (message_id, role, content, utc_now(), episode_id),
            )
        return message_id

    def recent(self, limit: int = 8):
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_messages ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows][::-1]

    def _semantic_text(self, text: str | None) -> str:
        return " ".join((text or "").strip().split())

    def _clip_text(self, text: str | None, max_len: int = 280) -> str:
        if not text:
            return ""
        text = " ".join(str(text).strip().split())
        if len(text) > max_len:
            return text[:max_len].rstrip() + "..."
        return text

    def _load_recent_messages(self, scan_limit: int = 800) -> list[dict[str, Any]]:
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_messages ORDER BY created_at DESC LIMIT ?",
                (scan_limit,),
            ).fetchall()
        messages = [dict(r) for r in rows]
        messages.reverse()
        return messages

    def _semantic_rank_messages(
        self,
        query_text: str,
        *,
        scan_limit: int = 300,
        min_similarity: float = 0.35,
    ) -> tuple[list[dict[str, Any]], list[tuple[float, int, list[str], dict[str, Any]]]]:
        messages = self._load_recent_messages(scan_limit=scan_limit)
        prepared_query = self._semantic_text(query_text)
        if not prepared_query or not messages:
            return messages, []

        query_embedding = embed_text(prepared_query, kind="query")
        if not query_embedding:
            return messages, []

        candidates: list[tuple[int, dict[str, Any]]] = []
        texts: list[str] = []
        for idx, message in enumerate(messages):
            text = self._semantic_text(message.get("content"))
            if not text:
                continue
            candidates.append((idx, message))
            texts.append(text)

        if not texts:
            return messages, []

        embeddings = embed_texts(texts, kind="passage")
        scored: list[tuple[float, int, list[str], dict[str, Any]]] = []
        for (idx, message), embedding in zip(candidates, embeddings):
            similarity = cosine_similarity(query_embedding, embedding)
            if similarity < min_similarity:
                continue
            score = similarity + (0.01 if message.get("role") == "user" else 0.0)
            scored.append((score, idx, [], message))

        scored.sort(key=lambda item: (item[0], item[3].get("created_at") or ""), reverse=True)
        return messages, scored

    def _build_window(
        self,
        messages: list[dict[str, Any]],
        anchor_index: int,
        before: int,
        after: int,
    ) -> list[dict[str, Any]]:
        start = max(0, anchor_index - before)
        end = min(len(messages), anchor_index + after + 1)
        window: list[dict[str, Any]] = []

        for idx in range(start, end):
            row = messages[idx]
            window.append(
                {
                    "id": row.get("id"),
                    "role": row.get("role"),
                    "content": self._clip_text(row.get("content"), max_len=260),
                    "created_at": row.get("created_at"),
                    "episode_id": row.get("episode_id"),
                    "is_anchor": idx == anchor_index,
                }
            )

        return window

    def search(self, query: str, limit: int = 5):
        _messages, scored = self._semantic_rank_messages(query, scan_limit=300, min_similarity=0.35)

        results: list[dict[str, Any]] = []
        for score, _, matched_terms, message in scored[:limit]:
            results.append(
                {
                    "id": message.get("id"),
                    "role": message.get("role"),
                    "content": self._clip_text(message.get("content"), max_len=280),
                    "created_at": message.get("created_at"),
                    "episode_id": message.get("episode_id"),
                    "match_score": round(score, 2),
                    "matched_terms": matched_terms[:8],
                }
            )
        return results

    def search_with_context(self, query: str, limit: int = 3, before: int = 2, after: int = 2):
        messages, scored = self._semantic_rank_messages(query, scan_limit=300, min_similarity=0.35)

        results: list[dict[str, Any]] = []
        used_ids: set[str] = set()

        for score, idx, matched_terms, message in scored:
            message_id = str(message.get("id") or "")
            if message_id in used_ids:
                continue
            used_ids.add(message_id)

            results.append(
                {
                    "match_type": "semantic_query",
                    "match_score": round(score, 4),
                    "matched_terms": matched_terms[:8],
                    "anchor_message": {
                        "id": message.get("id"),
                        "role": message.get("role"),
                        "content": self._clip_text(message.get("content"), max_len=280),
                        "created_at": message.get("created_at"),
                        "episode_id": message.get("episode_id"),
                    },
                    "window": self._build_window(messages, idx, before=before, after=after),
                }
            )

            if len(results) >= limit:
                break

        return results

    def find_context_by_anchor_text(
        self,
        anchor_text: str,
        limit: int = 2,
        before: int = 2,
        after: int = 2,
        match_type: str = "anchor_lookup",
    ):
        if not (anchor_text or "").strip():
            return []

        messages, scored = self._semantic_rank_messages(
            anchor_text,
            scan_limit=300,
            min_similarity=0.38,
        )

        results: list[dict[str, Any]] = []
        used_ids: set[str] = set()

        for score, idx, matched_terms, message in scored:
            message_id = str(message.get("id") or "")
            if message_id in used_ids:
                continue
            used_ids.add(message_id)

            results.append(
                {
                    "match_type": match_type,
                    "match_score": round(score, 4),
                    "matched_terms": matched_terms[:8],
                    "anchor_message": {
                        "id": message.get("id"),
                        "role": message.get("role"),
                        "content": self._clip_text(message.get("content"), max_len=280),
                        "created_at": message.get("created_at"),
                        "episode_id": message.get("episode_id"),
                    },
                    "window": self._build_window(messages, idx, before=before, after=after),
                }
            )

            if len(results) >= limit:
                break

        return results
