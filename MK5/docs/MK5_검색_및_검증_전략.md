# MK5 검색 및 검증 전략

## 1. 목표
MK5의 검색은 “모르면 인터넷 검색해서 답한다”가 아니다.
검색의 목적은 **현재 그래프가 비어 있는 부분만 국소적으로 보강**해서,
그 결과를 다시 그래프에 넣고 사고를 재개하는 것이다.

즉 검색은 answer-generation 보조가 아니라,
**graph completion / evidence enrichment**에 가깝다.

---

## 2. 기본 원칙

### 2-1. graph-first
- search 필요 판단은 그래프/사고 계층이 한다.
- 모델은 search 여부를 최종 결정하지 않는다.

### 2-2. slot-level search
- 질문 전체를 한 방에 search하지 않는다.
- 질문에서 entity / aspect slot을 뽑고,
- 그래프가 비어 있는 slot만 search한다.

### 2-3. provenance-preserving
- 검색 결과는 반드시 provider / source_provenance / trust_hint와 함께 들어간다.

### 2-4. error-visible
- 검색 실패는 실패처럼 보인다.
- provider error와 no result를 구분한다.

### 2-5. grounded response only
- grounding되지 않은 slot은 단정하지 않는다.

---

## 3. 권장 파이프라인
1. `QuestionSlotPlanner`
   - entities 추출
   - aspects 추출
2. `GraphCoverageEvaluator`
   - covered_slots 계산
   - missing_slots 계산
3. `MissingSlotSearchPlanner`
   - missing slot만 query로 변환
4. backend execution
5. search ingest
6. re-activation
7. re-thinking
8. conclusion / verbalization

---

## 4. search need 판정 기준
### search 필요 true
- 새 entity가 들어왔는데 grounding 없음
- 비교 축(aspect)이 늘었는데 해당 aspect coverage 없음
- conflict가 있는데 corroboration 가능한 대상임
- slot planner 실패 + multi-entity/multi-aspect 요청

### search 필요 false
- 현재 질문의 모든 slot이 충분히 covered
- 검색으로 얻을 수 없는 대상이고 내부 근거가 충분함
- 단순 memory probe / acknowledgment

---

## 5. conflict double-check 정책
현재 대화에서 나온 중요한 방향:

> 기존 그래프와 충돌하면,
> 검색 가능한 대상에 대해 external search로 더블체크하고,
> corroboration 되면 trust를 올리고,
> threshold를 넘으면 graph update를 수행한다.

이건 매우 좋은 방향이다.
다만 정보는 “사용자 vs 세계”로 이분화하기보다,
**모든 정보가 대상(entity)에 종속되고, 출처/검증 가능성이 별도 축으로 붙는다**고 보는 편이 더 일관된다.

즉:
- entity에 대한 claim
- provenance
- corroboration 가능성
- trust dynamics
를 함께 본다.

---

## 6. 디버그에 반드시 보여야 하는 것
- `planning_attempted`
- `query_triggered`
- `requested_slots`
- `covered_slots`
- `missing_slots`
- `issued_slot_queries`
- `grounded_terms`
- `missing_terms`
- `provider_errors`
- `error`

---

## 7. 앞으로의 고도화 방향
### 1차
- slot planner 안정화
- fail-open to search
- provider error visibility

### 2차
- trusted_search 다중 backend
- pairwise / grouped slot query batching
- `missing_aspects` 계산

### 3차
- conflict-driven corroboration
- search 결과 기반 trust 상승 / revision trigger
- post-search synthesis 강화
