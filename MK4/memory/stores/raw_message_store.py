import uuid
from typing import Any

from memory.db import connection_context, utc_now


STOPWORDS = {
    "그", "이", "저", "것", "수", "좀", "더", "정말", "진짜", "그냥",
    "대한", "관련", "기억", "예전", "이전", "최근", "현재", "내용", "부분",
    "what", "when", "where", "which", "about", "that", "this", "with",
    "from", "have", "your", "their", "into", "were", "been", "there",
}


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

    def _normalize_text(self, text: str | None) -> str:
        return " ".join((text or "").strip().split()).lower()

    def _clip_text(self, text: str | None, max_len: int = 280) -> str:
        if not text:
            return ""
        text = " ".join(str(text).strip().split())
        if len(text) > max_len:
            return text[:max_len].rstrip() + "..."
        return text

    def _tokenize(self, text: str | None) -> list[str]:
        raw = self._normalize_text(text)
        tokens: list[str] = []
        current: list[str] = []

        for ch in raw:
            if ch.isalnum() or ch == "_" or ("가" <= ch <= "힣"):
                current.append(ch)
            else:
                if current:
                    token = "".join(current)
                    if len(token) >= 2 and token not in STOPWORDS:
                        tokens.append(token)
                    current = []

        if current:
            token = "".join(current)
            if len(token) >= 2 and token not in STOPWORDS:
                tokens.append(token)

        seen: set[str] = set()
        deduped: list[str] = []
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            deduped.append(token)
        return deduped

    def _load_recent_messages(self, scan_limit: int = 800) -> list[dict[str, Any]]:
        with connection_context() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_messages ORDER BY created_at DESC LIMIT ?",
                (scan_limit,),
            ).fetchall()
        messages = [dict(r) for r in rows]
        messages.reverse()
        return messages

    def _score_message(self, query: str, message: dict[str, Any]) -> tuple[float, list[str]]:
        content = self._normalize_text(message.get("content"))
        if not content:
            return 0.0, []

        query_normalized = self._normalize_text(query)
        query_tokens = self._tokenize(query)

        score = 0.0
        matched_terms: list[str] = []

        if query_normalized and query_normalized in content:
            score += 8.0
            matched_terms.append(query_normalized[:80])

        for token in query_tokens:
            if token in content:
                score += 2.0
                matched_terms.append(token)

        if message.get("role") == "user":
            score += 0.2

        return score, matched_terms

    def _score_anchor_text(self, anchor_text: str, message: dict[str, Any]) -> tuple[float, list[str]]:
        content = self._normalize_text(message.get("content"))
        if not content:
            return 0.0, []

        anchor_normalized = self._normalize_text(anchor_text)
        anchor_tokens = self._tokenize(anchor_text)

        score = 0.0
        matched_terms: list[str] = []

        if anchor_normalized:
            short_anchor = anchor_normalized[:180]
            if short_anchor and short_anchor in content:
                score += 7.0
                matched_terms.append(short_anchor[:80])

        for token in anchor_tokens[:12]:
            if token in content:
                score += 1.5
                matched_terms.append(token)

        return score, matched_terms

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
        messages = self._load_recent_messages(scan_limit=800)
        scored: list[tuple[float, int, list[str], dict[str, Any]]] = []

        for idx, message in enumerate(messages):
            score, matched_terms = self._score_message(query, message)
            if score <= 0:
                continue
            scored.append((score, idx, matched_terms, message))

        scored.sort(key=lambda item: (item[0], item[3].get("created_at") or ""), reverse=True)

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
        messages = self._load_recent_messages(scan_limit=800)
        scored: list[tuple[float, int, list[str], dict[str, Any]]] = []

        for idx, message in enumerate(messages):
            score, matched_terms = self._score_message(query, message)
            if score <= 0:
                continue
            scored.append((score, idx, matched_terms, message))

        scored.sort(key=lambda item: (item[0], item[3].get("created_at") or ""), reverse=True)

        results: list[dict[str, Any]] = []
        used_ids: set[str] = set()

        for score, idx, matched_terms, message in scored:
            message_id = str(message.get("id") or "")
            if message_id in used_ids:
                continue
            used_ids.add(message_id)

            results.append(
                {
                    "match_type": "query_direct",
                    "match_score": round(score, 2),
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
        match_type: str = "anchor_fallback",
    ):
        if not (anchor_text or "").strip():
            return []

        messages = self._load_recent_messages(scan_limit=800)
        scored: list[tuple[float, int, list[str], dict[str, Any]]] = []

        for idx, message in enumerate(messages):
            score, matched_terms = self._score_anchor_text(anchor_text, message)
            if score <= 0:
                continue
            scored.append((score, idx, matched_terms, message))

        scored.sort(key=lambda item: (item[0], item[3].get("created_at") or ""), reverse=True)

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
                    "match_score": round(score, 2),
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