class EpisodeStore:
    """
    episode는 active / compressed / dropped 상태를 가진다.
    3개월 이상 참조 없거나 correction/profile에 반영되면 compressed 후보.
    6개월 이상 참조 없고 단순 단편 내용이면 dropped 후보.
    pinned는 삭제 금지.
    """

    def create_episode(self, topic: str, summary: str, raw_ref: str | None = None):
        raise NotImplementedError

    def reference(self, episode_id: str):
        raise NotImplementedError

    def find_relevant(self, query: str, limit: int = 5):
        raise NotImplementedError

    def transition_state(self):
        raise NotImplementedError
