# MK5 Slimmed Runtime

이 버전은 **concept-access 중심 런타임**을 유지하면서, 답변이 그래프 전체를 따라가던 문제를 줄이기 위해 다음 두 기능을 다시 포함한 정리본입니다.

## 다시 포함한 핵심 기능
- `ConceptDifferentiationService`
  - partial_reuse 누적, shared neighbor, high-severity contradiction을 바탕으로
  - `concept/flow | concept/neutral | concept/conflict` 엣지를 다시 형성합니다.
- `IntentManager`
  - 현재 주제와 이전 주제의 연속성을 다시 계산합니다.
  - `continued_topic | related_topic | shifted_topic`를 기반으로 사고/설명 초점을 정리합니다.

## 현재 런타임 핵심 흐름
1. 입력 ingest
2. ActivationEngine이 local graph 구성
3. 현재 질문에서 **핵심 topic term** 추출
4. ThoughtEngine
   - contradiction
   - trust
   - revision
   - concept differentiation
   - intent/topic following
   - conclusion
5. SearchSidecar
   - 현재 턴 생성 노드는 grounding 근거에서 제외
   - 질문 핵심 topic term 기준으로 search need 판단
6. verbalization

## 이번 정리에서 바뀐 점
- `current_topic_terms`를 아무 concept 전체가 아니라,
  - 질문 문장 우선
  - 그 직전 문맥 보조
  - seed activation + edge degree 반영
  방식으로 좁혔습니다.
- `activated_concepts`도 전 노드 나열이 아니라
  - topic term과 seed node를 우선한 **요약 목록**으로 제한합니다.
- search need는 가능한 한 `current_topic_terms`를 우선 사용합니다.
- 현재 입력에서 방금 생성된 노드는 search grounding 근거에서 제외합니다.
- search query는 concept 결합 없이 **개별 entity 개념 단위**로 발행합니다.

## 여전히 제거/비활성화된 층
- PatternDetector
- TemporaryEdgeService
- ModelFeedbackService
- ModelEdgeAssertionService
- ConnectTypePromotionService
- revision rule analytics / tuner / scheduler / override automation

## 의도
- 그래프 저장은 넓게 하되,
- 사고/주제 따라가기/검색 의무는 **핵심 개념 중심으로 좁히는 것**이 현재 목적입니다.
- 즉, `안녕`, `나는`, `지금` 같은 개념이 그래프에는 들어갈 수 있어도,
  답변 중심과 검색 의무까지 그대로 끌고 가지는 않도록 정리한 버전입니다.
