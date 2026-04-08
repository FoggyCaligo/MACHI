class CorrectionStore:
    """
    correction active queue는 최근 5개만 유지.
    profile에 반영된 오래된 correction은 제거 대상이 된다.
    """

    def add_correction(self, topic: str, content: str, reason: str, source: str = "user_explicit"):
        raise NotImplementedError

    def list_active(self, limit: int = 5):
        raise NotImplementedError

    def mark_applied(self, correction_id: str):
        raise NotImplementedError

    def trim_active_queue(self, keep: int = 5):
        raise NotImplementedError
