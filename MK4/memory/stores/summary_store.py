class SummaryStore:
    def upsert_topic_summary(self, topic: str, content: str, source_episode_ids: list[str]):
        raise NotImplementedError

    def get_by_topic(self, topic: str):
        raise NotImplementedError
