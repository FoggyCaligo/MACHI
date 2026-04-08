from memory.db import get_connection


class ProfileStore:
    """
    topic별 현재 profile과 직전 2개 history만 유지.
    새 profile이 active가 되면 기존 active는 superseded 처리하고,
    오래된 superseded는 topic당 최대 2개만 유지하도록 정리한다.
    """

    def get_active_by_topic(self, topic: str):
        raise NotImplementedError

    def insert_profile(self, topic: str, content: str, source: str, confidence: float = 1.0):
        raise NotImplementedError

    def trim_history(self, topic: str, keep_superseded: int = 2):
        raise NotImplementedError
