from memory.stores.profile_store import ProfileStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.summary_store import SummaryStore
from memory.stores.episode_store import EpisodeStore
from memory.stores.state_store import StateStore
from memory.stores.raw_message_store import RawMessageStore


class ResponseRetriever:
    def __init__(self) -> None:
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.summary_store = SummaryStore()
        self.episode_store = EpisodeStore()
        self.state_store = StateStore()
        self.raw_message_store = RawMessageStore()

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

    def _merge_ranked_rows(self, primary: list[dict], contextual: list[dict], *, limit: int) -> list[dict]:
        return self._dedupe_rows([*primary, *contextual], limit=limit)

    def _load_active_topic_context(self) -> dict:
        topic_id = self.state_store.get_active_topic_id()
        if not topic_id:
            return {
                "profiles": [],
                "corrections": [],
                "summaries": [],
            }

        profile = self.profile_store.get_active_by_topic(topic_id=topic_id)
        corrections = self.correction_store.list_active_by_topic(topic_id=topic_id, limit=1)
        summary = self.summary_store.get_by_topic(topic_id=topic_id)

        return {
            "profiles": [profile] if profile else [],
            "corrections": corrections,
            "summaries": [summary] if summary else [],
        }

    def retrieve(self, user_message: str) -> dict:
        searched_profiles = self.profile_store.search(user_message, limit=2, include_general=False)
        searched_corrections = self.correction_store.search(user_message, limit=1)
        searched_summaries = self.summary_store.search(user_message, limit=1)
        episodes = self.episode_store.find_relevant(user_message, limit=2)

        active_topic_context = self._load_active_topic_context()
        contextual_profiles = active_topic_context["profiles"]
        contextual_corrections = active_topic_context["corrections"]
        contextual_summaries = active_topic_context["summaries"]

        profiles = self._merge_ranked_rows(searched_profiles, contextual_profiles, limit=2)
        corrections = self._merge_ranked_rows(searched_corrections, contextual_corrections, limit=1)
        summaries = self._merge_ranked_rows(searched_summaries, contextual_summaries, limit=1)

        raw_recent_messages = self.raw_message_store.recent(limit=10)
        recent_messages = self._filter_recent_messages(
            raw_recent_messages,
            user_message=user_message,
            keep=4,
        )

        states = self._filter_states(self.state_store.get_all(), keep=2)

        for episode in episodes:
            if episode.get("id"):
                self.episode_store.reference(episode["id"])

        return {
            "profiles": profiles,
            "corrections": corrections,
            "summaries": summaries,
            "episodes": episodes,
            "states": states,
            "recent_messages": recent_messages,
        }
