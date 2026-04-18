# MK5 Slimmed Runtime

이 버전은 **search-before-think + meaning-analysis** 기준의 중간 리팩토링 상태다.

## 현재 런타임 흐름
1. user input ingest
2. ingest에서 생성된 `MeaningBlock` 후보 재사용
3. LLM이 후보들에 대해
   - 핵심도
   - 검색 정책
   - 업데이트 필요성
   을 라벨링
4. direct access
5. usable하지 않은 핵심 unit 자동 search
6. search ingest
7. activation 1회
8. think 1회
9. verbalization
10. assistant snapshot 저장 (full graph ingest 없음)

## direct access 정책
노드 존재만으로 성공으로 치지 않는다.

다음 중 하나면 search 대상이 될 수 있다.
- `node_missing`
- `mention_only`
- `grounded_but_stale`

다음만 바로 usable하다.
- `grounded_and_usable`

`local_only`는 외부 검색 대신 현재 시스템/현재 대화/로컬 그래프만 본다.

## LLM의 역할
LLM은 문장을 다시 거대한 의미 노드로 만드는 용도가 아니다.
역할은 다음으로 제한된다.
- 현재 질문의 핵심 키워드 식별
- 배경 키워드 식별
- ignore 대상 식별
- freshness / local_only 성격 라벨링

즉,
- 저장은 정규식 기반 후보를 넓게
- 판단은 LLM이 좁게
라는 원칙이다.

## 제거/비활성 유지
- PatternDetector
- TemporaryEdgeService
- ModelFeedbackService
- ModelEdgeAssertionService
- ConnectTypePromotionService
- revision analytics / tuner / scheduler / override automation

## 추가로 주의할 점
이 버전은 Step B 기준이므로,
- 의미 라벨링은 들어왔지만
- 아직 query focus와 conclusion summary가 완전히 clause-aware 하지는 않을 수 있다.

즉 다음 단계는
- query focus를 문장/절 중심으로 더 안정화하고
- conclusion이 그래프 전체가 아니라 질문 초점을 더 직접 따라가게 하는 것
이다.

- 입력 의미 분석은 더 이상 생성형 LLM을 호출하지 않고, 정규식 후보 + 코사인 유사도 기반 라벨링으로 처리한다.
