from memory.stores.profile_store import ProfileStore
from memory.stores.correction_store import CorrectionStore
from memory.stores.episode_store import EpisodeStore
from memory.stores.state_store import StateStore
from memory.stores.summary_store import SummaryStore
from memory.summarization.profile_rebuilder import ProfileRebuilder


class ConflictPolicy:
    def __init__(self) -> None:
        self.profile_store = ProfileStore()
        self.correction_store = CorrectionStore()
        self.episode_store = EpisodeStore()
        self.state_store = StateStore()
        self.summary_store = SummaryStore()
        self.profile_rebuilder = ProfileRebuilder()

    def apply(self, extracted: dict) -> None:
        touched_topics: set[tuple[str | None, str]] = set()

        for state in extracted.get("states", []):
            key = state["key"]
            value = state.get("value", "")
            if key == "active_topic_id" and not value:
                continue
            self.state_store.set_state(key, value, state.get("source", "user_explicit"))

        for profile in extracted.get("profiles", []):
            topic = profile.get("topic") or profile.get("topic_summary") or "general"
            topic_id = profile.get("topic_id")
            self.profile_store.insert_profile(
                topic=topic,
                content=profile["content"],
                source=profile.get("source", "user_explicit"),
                confidence=profile.get("confidence", 1.0),
                topic_id=topic_id,
            )
            touched_topics.add((topic_id, topic))

        for episode in extracted.get("episodes", []):
            topic = episode.get("topic") or episode.get("topic_summary") or "general"
            topic_id = episode.get("topic_id")
            self.episode_store.create_episode(
                topic=topic,
                topic_id=topic_id,
                summary=episode["summary"],
                raw_ref=episode.get("raw_ref"),
                importance=episode.get("importance", 0.5),
            )
            touched_topics.add((topic_id, topic))

        for correction in extracted.get("corrections", []):
            topic = correction.get("topic") or correction.get("topic_summary") or "general"
            topic_id = correction.get("topic_id")
            active_profile = self.profile_store.get_active_by_topic(topic=topic, topic_id=topic_id)
            supersedes_profile_id = None
            if active_profile and active_profile["content"].strip() != correction["content"].strip():
                supersedes_profile_id = active_profile["id"]
            self.correction_store.add_correction(
                topic=topic,
                topic_id=topic_id,
                content=correction["content"],
                reason=correction.get("reason", "explicit_correction"),
                source=correction.get("source", "user_explicit"),
                supersedes_profile_id=supersedes_profile_id,
            )
            touched_topics.add((topic_id, topic))

        for topic_id, topic in touched_topics:
            self.profile_rebuilder.rebuild_topic(topic=topic, topic_id=topic_id)
