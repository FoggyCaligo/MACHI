from memory.stores.profile_store import ProfileStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.summary_store import SummaryStore


class ProfileRebuilder:
    def __init__(self) -> None:
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.summary_store = SummaryStore()

    def rebuild_topic(self, topic: str) -> None:
        active_profile = self.profile_store.get_active_by_topic(topic)
        corrections = self.correction_store.list_active_by_topic(topic, limit=5)

        if corrections:
            latest = corrections[0]
            new_content = latest['content']
            source = 'rebuilt_from_correction'
            new_profile_id = self.profile_store.insert_profile(topic, new_content, source=source, confidence=1.0)
            self.summary_store.upsert_topic_summary(
                topic=topic,
                content=new_content,
                source_episode_ids=[],
            )
            self.correction_store.mark_applied(latest['id'])
            return

        if active_profile:
            self.summary_store.upsert_topic_summary(
                topic=topic,
                content=active_profile['content'],
                source_episode_ids=[],
            )
