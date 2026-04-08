class RecallRetriever:
    """
    1차 recall 응답은 아래 4개 중심:
    1. 기억 여부
    2. 에피소드 요약
    3. 관련 시점/맥락
    4. 현재 이해에 미친 영향

    원문 일부/전체는 후속 recall depth 요청 시 확장한다.
    """

    def retrieve(self, query: str) -> dict:
        return {
            "found": False,
            "episode_summary": None,
            "time_context": None,
            "impact_on_current_understanding": None,
            "raw_available": False,
        }
