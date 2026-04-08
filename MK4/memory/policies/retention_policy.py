class RetentionPolicy:
    """
    episode lifecycle:
    - correction/profile 반영 or 3개월 미참조 -> compressed
    - 6개월 미참조 + 단순/단편 + unpinned -> dropped

    correction lifecycle:
    - active queue 최근 5개 유지
    - profile 반영된 오래된 correction 제거

    profile history:
    - topic별 이전 2개만 유지
    """

    def run(self) -> None:
        pass
