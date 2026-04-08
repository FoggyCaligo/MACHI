class ProfileRebuilder:
    """
    always-on rebuild가 아니라 conflict-triggered, topic-scoped rebuild만 수행.
    """

    def rebuild_topic(self, topic: str) -> None:
        raise NotImplementedError
