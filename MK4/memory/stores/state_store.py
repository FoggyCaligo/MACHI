class StateStore:
    """
    기분/상태는 append하지 않고 최신 슬롯만 유지.
    예: current_mood, current_stress, current_focus_project
    """

    def set_state(self, key: str, value: str, source: str = "user_explicit"):
        raise NotImplementedError

    def get_state(self, key: str):
        raise NotImplementedError

    def get_all(self):
        raise NotImplementedError
