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
        """
        recent_messages를 프롬프트에 넣기 전에 정제한다.

        규칙:
        1) 빈 content 제거
        2) 현재 user_message와 동일한 마지막 user 턴 제거
           - orchestrator에서 user를 먼저 저장하는 구조일 때 중복 방지
        3) 너무 긴 content는 잘라서 전달
        4) 최근 keep개만 유지
        """
        cleaned: list[dict] = []
        normalized_user_message = " ".join((user_message or "").strip().split())

        skipped_current_user = False

        # 뒤에서부터 보면서 "현재 질문과 같은 마지막 user 메시지 1개"만 제거
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
            if key == "active_topic_id":
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

    def retrieve(self, user_message: str) -> dict:
        # E4B 기준으로 retrieval 규모를 줄인다.
        profiles = self.profile_store.search(user_message, limit=2, include_general=False)
        if not profiles:
            profiles = self.profile_store.get_active_profiles(exclude_general=True)[:2]

        corrections = self.correction_store.search(user_message, limit=1)
        summaries = self.summary_store.search(user_message, limit=1)
        episodes = self.episode_store.find_relevant(user_message, limit=2)

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