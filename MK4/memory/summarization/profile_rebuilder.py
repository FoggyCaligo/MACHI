from memory.stores.profile_store import ProfileStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.summary_store import SummaryStore


class ProfileRebuilder:
    def __init__(self) -> None:
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.summary_store = SummaryStore()

    def rebuild_topic(self, topic: str | None = None, topic_id: str | None = None) -> None:
        active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
        corrections = self.correction_store.list_active_by_topic(topic=topic, topic_id=topic_id, limit=5)

        if corrections:
            latest = corrections[0]
            new_content = latest['content']
            source = 'rebuilt_from_correction'
            self.profile_store.insert_profile(
                latest.get('topic') or topic or 'general',
                new_content,
                source=source,
                confidence=1.0,
                topic_id=latest.get('topic_id') or topic_id,
            )
            self.summary_store.upsert_topic_summary(
                topic=latest.get('topic') or topic or 'general',
                content=new_content,
                source_episode_ids=[],
                topic_id=latest.get('topic_id') or topic_id,
            )
            self.correction_store.mark_applied(latest['id'])
            return

        if active_profile:
            self.summary_store.upsert_topic_summary(
                topic=active_profile.get('topic') or topic or 'general',
                content=active_profile['content'],
                source_episode_ids=[],
                topic_id=active_profile.get('topic_id') or topic_id,
            )
