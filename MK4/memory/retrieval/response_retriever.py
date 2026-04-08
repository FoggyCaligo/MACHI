class ResponseRetriever:
    """
    일반 응답용 retrieval.
    반환 대상:
    - relevant profiles
    - active corrections
    - relevant summaries
    - recent / relevant episodes
    - current states
    """

    def retrieve(self, user_message: str) -> dict:
        return {
            "profiles": [],
            "corrections": [],
            "summaries": [],
            "episodes": [],
            "states": [],
        }
