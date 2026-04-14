from memory.stores.profile_store import ProfileStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.summary_store import SummaryStore
from memory.stores.episode_store import EpisodeStore
from memory.stores.state_store import StateStore
from memory.stores.raw_message_store import RawMessageStore
from memory.stores.candidate_profile_store import CandidateProfileStore
from memory.retrieval.source_lookup_service import SourceLookupService


class ResponseRetriever:
    def __init__(self) -> None:
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.summary_store = SummaryStore()
        self.episode_store = EpisodeStore()
        self.state_store = StateStore()
        self.raw_message_store = RawMessageStore()
        self.candidate_profile_store = CandidateProfileStore()
        self.source_lookup_service = SourceLookupService()

    def _clean_text(self, text: str | None, max_len: int = 300) -> str:
        if not text:
            return ""
        text = " ".join(text.strip().split())
        if len(text) > max_len:
            return text[:max_len].rstrip() + "..."
        return text

    def _filter_recent_messages(self, messages: list[dict], user_message: str, keep: int = 4) -> list[dict]:
        cleaned: list[dict] = []
        normalized_user_message = " ".join((user_message or "").strip().split())

        skipped_current_user = False

        for msg in reversed(messages):
            role = msg.get("role", "")
            content = self._clean_text(msg.get("content", ""), max_len=300)

            if not content:
                continue

            if (
                not skipped_current_user
                and role == "user"
                and normalized_user_message
                and content == normalized_user_message
            ):
                skipped_current_user = True
                continue

            cleaned.append(
                {
                    "id": msg.get("id"),
                    "role": role,
                    "content": content,
                    "created_at": msg.get("created_at"),
                    "episode_id": msg.get("episode_id"),
                }
            )

            if len(cleaned) >= keep:
                break

        cleaned.reverse()
        return cleaned

    def _filter_states(self, states: list[dict], keep: int = 2) -> list[dict]:
        filtered: list[dict] = []

        for state in states:
            key = self._clean_text(state.get("key", ""), max_len=80)
            if key in {"active_topic_id", "active_topic_summary"}:
                continue
            value = self._clean_text(state.get("value", ""), max_len=160)

            if not key or not value:
                continue

            filtered.append(
                {
                    "key": key,
                    "value": value,
                    "updated_at": state.get("updated_at"),
                    "source": state.get("source"),
                }
            )

            if len(filtered) >= keep:
                break

        return filtered

    def _dedupe_rows(self, rows: list[dict], *, limit: int) -> list[dict]:
        """Deduplicate rows by ID and content key. Kept for future use if needed."""
        deduped: list[dict] = []
        seen_ids: set[str] = set()
        seen_content_keys: set[tuple[str, str, str]] = set()

        for row in rows:
            row_id = str(row.get("id") or "").strip()
            if row_id:
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
            else:
                content_key = (
                    str(row.get("topic_id") or "").strip(),
                    str(row.get("topic") or row.get("topic_summary") or row.get("topic_name") or "").strip(),
                    str(row.get("content") or row.get("summary") or row.get("value") or "").strip(),
                )
                if content_key in seen_content_keys:
                    continue
                seen_content_keys.add(content_key)

            deduped.append(row)
            if len(deduped) >= limit:
                break

        return deduped

    def _load_active_topic_context(self) -> dict:
        topic_id = self.state_store.get_active_topic_id()
        if not topic_id:
            return {
                "profiles": [],
                "candidate_profiles": [],
                "corrections": [],
                "summaries": [],
            }

        profile = self.profile_store.get_active_by_topic(topic_id=topic_id)
        corrections = self.correction_store.list_active_by_topic(topic_id=topic_id, limit=1)
        summary = self.summary_store.get_by_topic(topic_id=topic_id)
        candidate_profiles = self.candidate_profile_store.list_active_by_topic(topic_id=topic_id, limit=2)

        return {
            "profiles": [profile] if profile else [],
            "candidate_profiles": candidate_profiles,
            "corrections": corrections,
            "summaries": [summary] if summary else [],
        }

    def _load_recent_global_corrections(self, limit: int = 2) -> list[dict]:
        return self.correction_store.list_active(limit=limit)

    def retrieve(self, user_message: str) -> dict:
        active_topic_id = self.state_store.get_active_topic_id()

        # Load active topic context only (no string-based search; embedding-based retrieval pending)
        active_topic_context = self._load_active_topic_context()
        contextual_profiles = active_topic_context["profiles"]  # max 1 per topic
        contextual_candidate_profiles = active_topic_context["candidate_profiles"]
        contextual_corrections = active_topic_context["corrections"]
        contextual_summaries = active_topic_context["summaries"]
        
        # Load recent global corrections as fallback
        recent_global_corrections = self._load_recent_global_corrections(limit=2)
        
        # Episode retrieval by semantic similarity (embedding-based)
        episodes = self.episode_store.find_relevant(user_message, limit=2)
        
        # Recent messages and states (no search; context-only)
        raw_recent_messages = self.raw_message_store.recent(limit=10)
        recent_messages = self._filter_recent_messages(
            raw_recent_messages,
            user_message=user_message,
            keep=4,
        )
        
        states = self._filter_states(self.state_store.get_all(), keep=2)

        recent_sources = self.source_lookup_service.lookup(
            user_message,
            limit=3,
            active_topic_id=active_topic_id,
        )
        
        # Mark episode references
        for episode in episodes:
            if episode.get("id"):
                self.episode_store.reference(episode["id"])

        return {
            "profiles": contextual_profiles,  # max 1 active profile from current topic
            "candidate_profiles": contextual_candidate_profiles,
            "corrections": contextual_corrections + recent_global_corrections,  # topic-local + global fallback
            "summaries": contextual_summaries,  # max 1 per topic
            "episodes": episodes,  # based on relevance search (pending embedding)
            "states": states,
            "recent_messages": recent_messages,
            "recent_sources": recent_sources,
        }
