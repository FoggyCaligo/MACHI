class ConflictPolicy:
    """
    우선순위:
    1. user explicit correction
    2. latest active correction
    3. active profile
    4. inferred memory

    새 correction이 profile과 충돌하면 topic-scoped rebuild를 트리거한다.
    이전 profile은 superseded로 남긴다.
    """

    def apply(self, extracted: dict) -> None:
        pass
