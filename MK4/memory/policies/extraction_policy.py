class ExtractionPolicy:
    """
    명시 정정 표현 우선 + 의미 충돌 검사 필수.
    correction / episode / state / discard 후보를 추출.
    """

    def extract(self, user_message: str, reply: str, update_plan: dict) -> dict:
        return {
            "profiles": [],
            "corrections": [],
            "episodes": [],
            "states": [],
            "discarded": [],
        }
