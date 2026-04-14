from memory.stores.profile_store import ProfileStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.episode_store import EpisodeStore
from memory.stores.summary_store import SummaryStore
from memory.stores.raw_message_store import RawMessageStore
from memory.stores.topic_store import TopicStore
from tools.text_embedding import cosine_similarity, embed_text, embed_texts


RECALL_TOPIC_LIMIT = 4
RECALL_TOPIC_MIN_SIMILARITY = 0.42
RECALL_MEMORY_MIN_SIMILARITY = 0.35


class RecallRetriever:
    def __init__(self) -> None:
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.episode_store = EpisodeStore()
        self.summary_store = SummaryStore()
        self.raw_message_store = RawMessageStore()
        self.topic_store = TopicStore()

    def _clip_text(self, text: str | None, max_len: int = 220) -> str:
        if not text:
            return ""
        text = " ".join(str(text).strip().split())
        if len(text) > max_len:
            return text[:max_len].rstrip() + "..."
        return text

    def _topic_label(self, row: dict) -> str:
        return self._clip_text(
            row.get("topic_summary") or row.get("topic_name") or row.get("topic") or "general",
            max_len=80,
        ) or "general"

    def _row_search_text(self, row: dict, preferred_keys: list[str]) -> str:
        parts = [self._topic_label(row)]
        for key in preferred_keys:
            value = self._clip_text(row.get(key), max_len=400)
            if value:
                parts.append(value)
        return "\n".join(part for part in parts if part)

    def _rank_rows_by_query(
        self,
        query: str,
        rows: list[dict],
        *,
        preferred_keys: list[str],
        limit: int,
        min_similarity: float = RECALL_MEMORY_MIN_SIMILARITY,
    ) -> list[dict]:
        normalized_query = " ".join((query or "").strip().split())
        if not normalized_query or not rows:
            return []

        query_embedding = embed_text(normalized_query, kind="query")
        if not query_embedding:
            return []

        candidates: list[dict] = []
        texts: list[str] = []
        for row in rows:
            text = self._row_search_text(row, preferred_keys)
            if not text:
                continue
            candidates.append(row)
            texts.append(text)

        if not texts:
            return []

        embeddings = embed_texts(texts, kind="passage")
        scored: list[dict] = []
        for row, embedding in zip(candidates, embeddings):
            similarity = cosine_similarity(query_embedding, embedding)
            if similarity < min_similarity:
                continue
            scored.append(
                {
                    **row,
                    "_recall_similarity": similarity,
                }
            )

        scored.sort(
            key=lambda item: (
                item.get("_recall_similarity", 0.0),
                item.get("updated_at") or item.get("created_at") or "",
            ),
            reverse=True,
        )

        return [
            {key: value for key, value in row.items() if key != "_recall_similarity"}
            for row in scored[:limit]
        ]

    def _load_active_summaries(self) -> list[dict]:
        summaries: list[dict] = []
        seen_ids: set[str] = set()

        for topic in self.topic_store.list_active_topics(limit=80):
            topic_id = str(topic.get("id") or "").strip() or None
            summary = self.summary_store.get_by_topic(topic_id=topic_id)
            if not summary:
                continue
            summary_id = str(summary.get("id") or "").strip()
            if summary_id and summary_id in seen_ids:
                continue
            if summary_id:
                seen_ids.add(summary_id)
            summaries.append(summary)

        general_summary = self.summary_store.get_by_topic(topic_id=None)
        if general_summary:
            summary_id = str(general_summary.get("id") or "").strip()
            if not summary_id or summary_id not in seen_ids:
                summaries.append(general_summary)

        return summaries

    def _build_impacts(
        self,
        corrections: list[dict],
        profiles: list[dict],
        summaries: list[dict],
    ) -> list[str]:
        impacts: list[str] = []

        for correction in corrections:
            topic = self._topic_label(correction)
            content = self._clip_text(correction.get("content"), max_len=180)
            impacts.append(f"정정 반영: [{topic}] {content}")

        for profile in profiles:
            topic = self._topic_label(profile)
            content = self._clip_text(profile.get("content"), max_len=180)
            impacts.append(f"현재 프로필: [{topic}] {content}")

        for summary in summaries:
            topic = self._topic_label(summary)
            content = self._clip_text(summary.get("content"), max_len=180)
            impacts.append(f"요약 기억: [{topic}] {content}")

        return impacts

    def _build_trace_block(self, rows: list[dict], include_status: bool = False) -> list[dict]:
        trace: list[dict] = []

        for row in rows:
            item = {
                "id": row.get("id"),
                "topic": self._topic_label(row),
                "content": self._clip_text(
                    row.get("content") or row.get("summary"),
                    max_len=220,
                ),
                "created_at": row.get("created_at") or row.get("updated_at"),
            }
            if include_status:
                item["status"] = row.get("status")
            trace.append(item)

        return trace

    def _build_episode_trace(self, episodes: list[dict]) -> list[dict]:
        trace: list[dict] = []

        for episode in episodes:
            trace.append(
                {
                    "id": episode.get("id"),
                    "topic": self._topic_label(episode),
                    "summary": self._clip_text(episode.get("summary"), max_len=220),
                    "raw_ref": self._clip_text(episode.get("raw_ref"), max_len=220),
                    "created_at": episode.get("created_at"),
                    "last_referenced_at": episode.get("last_referenced_at"),
                    "state": episode.get("state"),
                }
            )

        return trace

    def _build_topic_trace(self, topics: list[dict]) -> list[dict]:
        trace: list[dict] = []
        for topic in topics:
            trace.append(
                {
                    "id": topic.get("id"),
                    "name": self._clip_text(topic.get("name"), max_len=120),
                    "summary": self._clip_text(topic.get("summary"), max_len=180),
                    "similarity": round(float(topic.get("similarity") or 0.0), 4),
                }
            )
        return trace

    def retrieve(self, query: str) -> dict:
        episodes = self.episode_store.find_relevant(query, limit=3)
        semantic_topics = self.topic_store.find_similar_topics(
            text=query,
            limit=RECALL_TOPIC_LIMIT,
            min_similarity=RECALL_TOPIC_MIN_SIMILARITY,
        )
        profiles = self._rank_rows_by_query(
            query,
            self.profile_store.get_active_profiles(),
            preferred_keys=["content"],
            limit=3,
        )
        corrections = self._rank_rows_by_query(
            query,
            self.correction_store.list_active(limit=20),
            preferred_keys=["content", "reason"],
            limit=3,
        )
        summaries = self._rank_rows_by_query(
            query,
            self._load_active_summaries(),
            preferred_keys=["content"],
            limit=2,
        )

        for episode in episodes:
            if episode.get("id"):
                self.episode_store.reference(episode["id"])

        raw_expansions = self.raw_message_store.search_with_context(
            query=query,
            limit=2,
            before=2,
            after=2,
        )

        found = bool(episodes or corrections or profiles or summaries or raw_expansions)
        episode_summary = [self._clip_text(e.get("summary"), max_len=220) for e in episodes] if episodes else []
        time_context = [e["created_at"] for e in episodes if e.get("created_at")] if episodes else []

        impacts = self._build_impacts(
            corrections=corrections,
            profiles=profiles,
            summaries=summaries,
        )

        return {
            "found": found,
            "episode_summary": episode_summary or None,
            "time_context": time_context or None,
            "impact_on_current_understanding": impacts or None,
            "raw_available": bool(raw_expansions),
            "raw_expansions": raw_expansions or None,
            "trace": {
                "topics": self._build_topic_trace(semantic_topics),
                "episodes": self._build_episode_trace(episodes),
                "corrections": self._build_trace_block(corrections, include_status=True),
                "profiles": self._build_trace_block(profiles, include_status=True),
                "summaries": self._build_trace_block(summaries),
            },
        }
