from __future__ import annotations

from config import PROFILE_SEMANTIC_MATCH_THRESHOLD
from tools.text_embedding import cosine_similarity, embed_text


class ProfileEvidenceGraph:
    def __init__(self, *, topic_store=None) -> None:
        self.topic_store = topic_store
        self._embedding_cache: dict[str, list[float]] = {}

    def normalize_text(self, text: str | None) -> str:
        return " ".join((text or "").strip().split())

    def clip_text(self, text: str | None, max_len: int = 360) -> str:
        normalized = self.normalize_text(text)
        if not normalized:
            return ""
        if len(normalized) > max_len:
            return normalized[:max_len].rstrip() + "..."
        return normalized

    def content_embedding(self, text: str | None) -> list[float]:
        normalized = self.normalize_text(text)
        if not normalized:
            return []
        if normalized not in self._embedding_cache:
            self._embedding_cache[normalized] = embed_text(normalized, kind="passage")
        return self._embedding_cache[normalized]

    def semantic_similarity(self, left: str | None, right: str | None) -> float:
        left_embedding = self.content_embedding(left)
        right_embedding = self.content_embedding(right)
        return cosine_similarity(left_embedding, right_embedding)

    def same_meaning(
        self,
        left: str | None,
        right: str | None,
        *,
        threshold: float = PROFILE_SEMANTIC_MATCH_THRESHOLD,
    ) -> bool:
        normalized_left = self.normalize_text(left)
        normalized_right = self.normalize_text(right)
        if not normalized_left or not normalized_right:
            return False
        if normalized_left == normalized_right:
            return True
        return self.semantic_similarity(normalized_left, normalized_right) >= threshold

    def topic_label(self, topic: str | None = None, topic_id: str | None = None) -> str:
        if topic:
            return str(topic).strip() or "general"
        if topic_id and self.topic_store is not None:
            topic_row = self.topic_store.get_topic(topic_id)
            if topic_row:
                return str(topic_row.get("summary") or topic_row.get("name") or "general").strip() or "general"
        return "general"

    def topic_key(
        self,
        *,
        item: dict | None = None,
        topic: str | None = None,
        topic_id: str | None = None,
    ) -> str | None:
        if item is not None:
            topic = item.get("topic")
            topic_id = str(item.get("topic_id") or "").strip() or None

        if topic_id:
            return f"id:{topic_id}"

        normalized_topic = self.normalize_text(topic)
        if normalized_topic and normalized_topic.lower() != "general":
            return f"topic:{normalized_topic.lower()}"
        return None

    def dedupe_ranked_rows(self, ranked_rows: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen_keys: set[str] = set()

        for row in ranked_rows or []:
            lookup_key = str(row.get("lookup_key") or row.get("_lookup_key") or row.get("id") or "").strip()
            if not lookup_key or lookup_key in seen_keys:
                continue
            seen_keys.add(lookup_key)
            deduped.append(row)

        return deduped

    def _reference_key(self, item: dict) -> str:
        return str(item.get("_lookup_key") or item.get("lookup_key") or item.get("source_id") or item.get("id") or "").strip()

    def build_reference_trace(
        self,
        *,
        reference: dict,
        references: list[dict],
        ranked_rows: list[dict],
        active_topic_id: str | None = None,
    ) -> dict | None:
        topic_key = self.topic_key(item=reference)
        active_topic_match = bool(active_topic_id and str(reference.get("topic_id") or "").strip() == active_topic_id)
        reference_candidate = self.normalize_text(reference.get("candidate_content"))

        topic_support_count = 0
        candidate_support_count = 0
        for row in ranked_rows:
            if topic_key and self.topic_key(item=row) == topic_key:
                topic_support_count += 1
            if reference_candidate and self.same_meaning(reference_candidate, row.get("candidate_content")):
                candidate_support_count += 1

        reference_key = self._reference_key(reference)
        connections: list[dict] = []
        for other in references:
            if self._reference_key(other) == reference_key:
                continue

            via: list[str] = []
            if topic_key and self.topic_key(item=other) == topic_key:
                via.append("same_topic")
            if reference_candidate and self.same_meaning(reference_candidate, other.get("candidate_content")):
                via.append("same_candidate_meaning")

            if not via:
                continue

            connections.append(
                {
                    "label": self.normalize_text(other.get("label")) or self.normalize_text(other.get("source_kind")) or "source",
                    "source_kind": self.normalize_text(other.get("source_kind")) or None,
                    "topic": self.normalize_text(other.get("topic")) or None,
                    "candidate_content": self.clip_text(other.get("candidate_content"), max_len=120) or None,
                    "via": via,
                }
            )

        connections.sort(
            key=lambda item: (
                len(item.get("via") or []),
                item.get("label") or "",
            ),
            reverse=True,
        )

        if not active_topic_match and topic_support_count <= 1 and candidate_support_count <= 1 and not connections:
            return None

        return {
            "topic_anchor": self.normalize_text(reference.get("topic")) or None,
            "active_topic_match": active_topic_match,
            "topic_support_count": topic_support_count,
            "candidate_support_count": candidate_support_count,
            "connections": connections[:2],
        }

    def attach_reference_traces(
        self,
        references: list[dict],
        ranked_rows: list[dict],
        *,
        active_topic_id: str | None = None,
    ) -> list[dict]:
        if not references:
            return []

        deduped_ranked_rows = self.dedupe_ranked_rows(ranked_rows)
        traced: list[dict] = []

        for reference in references:
            enriched = dict(reference)
            trace = self.build_reference_trace(
                reference=enriched,
                references=references,
                ranked_rows=deduped_ranked_rows,
                active_topic_id=active_topic_id,
            )
            if trace:
                enriched["trace"] = trace
            cleaned = {
                key: value
                for key, value in enriched.items()
                if not str(key).startswith("_")
            }
            traced.append(cleaned)

        return traced
