class UpdateRetriever:
    """
    이번 턴이 어떤 업데이트를 발생시키는지 분류:
    - new_episode
    - new_correction
    - profile_reinforcement
    - state_update
    - discard
    """

    def classify(self, user_message: str, reply: str) -> dict:
        return {
            "actions": []
        }
