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
        touched_topics: set[str] = set()

        for state in extracted.get("states", []):
            self.state_store.set_state(state["key"], state["value"], state.get("source", "user_explicit"))

        for episode in extracted.get("episodes", []):
            self.episode_store.create_episode(
                topic=episode["topic"],
                summary=episode["summary"],
                raw_ref=episode.get("raw_ref"),
                importance=episode.get("importance", 0.5),
            )
            touched_topics.add(episode["topic"])

        for correction in extracted.get("corrections", []):
            active_profile = self.profile_store.get_active_by_topic(correction["topic"])
            supersedes_profile_id = None
            if active_profile and active_profile["content"].strip() != correction["content"].strip():
                supersedes_profile_id = active_profile["id"]
            self.correction_store.add_correction(
                topic=correction["topic"],
                content=correction["content"],
                reason=correction.get("reason", "explicit_correction"),
                source=correction.get("source", "user_explicit"),
                supersedes_profile_id=supersedes_profile_id,
            )
            touched_topics.add(correction["topic"])

        for topic in touched_topics:
            self.profile_rebuilder.rebuild_topic(topic)
