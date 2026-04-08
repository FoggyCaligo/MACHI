from memory.stores.episode_store import EpisodeStore
from memory.stores.summary_store import SummaryStore


class EpisodeCompressor:
    def __init__(self) -> None:
        self.episode_store = EpisodeStore()
        self.summary_store = SummaryStore()

    def compress(self, episode_id: str) -> None:
        # 1차 구현에서는 retention policy가 state만 바꾸고,
        # 향후 필요하면 topic summary에 흡수하는 방식으로 확장.
        self.episode_store.mark_compressed(episode_id)
