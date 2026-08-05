from memory.stores.profile_store import ProfileStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.summary_store import SummaryStore
from memory.stores.topic_store import TopicStore


class ProfileRebuilder:
    def __init__(self) -> None:
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.summary_store = SummaryStore()
        self.topic_store = TopicStore()

    def _correction_target_kind(self, reason: str | None) -> str:
        text = str(reason or "").strip()
        prefix, has_separator, _rest = text.partition(":")
        if has_separator and prefix in {"profile", "topic_fact", "response_behavior"}:
            return prefix
        return "topic_fact"

    def rebuild_topic(self, topic: str | None = None, topic_id: str | None = None) -> None:
        active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
        corrections = self.correction_store.list_active_by_topic(topic=topic, topic_id=topic_id, limit=5)

        latest_profile_correction = next(
            (item for item in corrections if self._correction_target_kind(item.get("reason")) == "profile"),
            None,
        )

        if latest_profile_correction:
            latest = latest_profile_correction
            new_content = latest['content']
            source = 'rebuilt_from_correction'
            resolved_topic_id = latest.get('topic_id') or topic_id
            topic_label = latest.get('topic_summary') or latest.get('topic_name') or topic or 'general'
            self.profile_store.insert_profile(
                topic_label,
                new_content,
                source=source,
                confidence=1.0,
                topic_id=resolved_topic_id,
            )
            self.summary_store.upsert_topic_summary(
                topic=topic_label,
                content=new_content,
                source_episode_ids=[],
                topic_id=resolved_topic_id,
            )
            self.correction_store.mark_applied(latest['id'])
            return

        if active_profile:
            topic_label = active_profile.get('topic_summary') or active_profile.get('topic_name') or topic or 'general'
            self.summary_store.upsert_topic_summary(
                topic=topic_label,
                content=active_profile['content'],
                source_episode_ids=[],
                topic_id=active_profile.get('topic_id') or topic_id,
            )
