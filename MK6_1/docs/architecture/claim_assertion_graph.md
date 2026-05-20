# MK6 Claim / Assertion Graph 정책

작성: 2026-05-18  
상태: skeleton 정책 v1  
범위: 사용자 발화, assistant 발화, 검색 결과, 정정/충돌을 케이스별 그래프가 아니라 일반 주장 구조로 처리

---

## 1. 핵심 결정

MK6는 `SelfClaimGraph`, `CorrectionGraph`, `PreferenceGraph`, `PlanGraph` 같은 케이스별 그래프를 계속 늘리지 않는다.

대신 모든 발화와 외부 정보는 우선 일반적인 `ClaimAssertion`으로 projection한다.

```text
ClaimAssertion
  - source
  - subject
  - object
  - provenance
  - temporal_scope
  - confidence
```

정정은 별도 CorrectionGraph가 아니다.

```text
새 ClaimAssertion
  → conflict
기존 AssertionState
```

즉 correction은 Claim 간 conflict 관계의 한 사례다.

---

## 2. 기본 primitive

현재 skeleton의 기본 primitive는 다음이다.

```text
ClaimAssertion
  발화/검색/시스템 정책에서 온 일반 주장 단위

AssertionState
  직전 응답 또는 현재 입력의 주장 상태 projection

ClaimConflict
  현재 assertion과 이전 assertion state 사이의 conflict 후보

ConclusionGraph
  ClaimConflict나 answer path가 언어화될 때 쓰이는 국소 그래프 projection
```

---

## 3. 사용자 자기진술 처리

사용자 자기진술도 별도 SelfClaimGraph를 만들지 않는다.

예:

```text
내 이름은 신재용이야.
난 과거에 개발자로 일했었어.
```

이 발화들은 모두 다음처럼 projection된다.

```text
ClaimAssertion
  source = 사용자
  provenance = user_statement
  subject/object = 현재 입력 그래프에서 나온 concept들
```

향후 subject binding이 고도화되면, 이 claim의 subject가 `ANCHOR_USER` 또는 `USER_PERSON::<surface>`로 resolve될 수 있다.

중요한 점:

```text
사용자 자기진술은 별도 그래프 타입이 아니다.
source가 사용자이고, subject가 사용자 쪽으로 resolve된 ClaimAssertion이다.
```

---

## 4. 정정 처리

기존 `CorrectionGraph`는 제거한다.

이전 구조:

```text
CorrectionGraph
PreviousAssistantState
build_correction_graph()
apply_correction_pressure()
```

새 구조:

```text
ClaimConflict
AssertionState
build_claim_conflict_graph()
apply_claim_conflict_pressure()
```

정정은 다음처럼 처리한다.

```text
current user assertion
  → conflict
previous assertion state
```

이 conflict는 초기 skeleton에서는 temporary edge로 만들어진다.  
WorldGraph 영구 반영은 후속 UpdateEngine 정책으로 분리한다.

---

## 5. ConclusionGraph와의 관계

`ConclusionGraph`는 더 이상 `graph_kind="correction"` 같은 케이스 타입을 갖지 않는다.

대신 conflict 여부는 구조에서 파생된다.

```text
ConclusionGraph.has_conflict_structure
  = conflict_paths 또는 exception_hashes가 있는가
```

GraphToLang은 `graph_kind`가 아니라 conflict 구조 존재 여부를 보고 ClaimConflict 섹션을 구성한다.

---

## 6. 금지 규칙

```text
1. SelfClaimGraph를 만들지 않는다.
2. CorrectionGraph를 만들지 않는다.
3. 선호/계획/관계/직업전환 같은 케이스별 그래프를 계속 추가하지 않는다.
4. 정정 여부를 문자열 패턴으로 판단하지 않는다.
5. 사용자 프로필을 사실 저장소로 쓰지 않는다.
```

---

## 7. TODO

```text
1. subject binding 고도화
   - ANCHOR_USER
   - USER_PROFILE
   - USER_PERSON::<surface>

2. temporal/state scope primitive 추가
   - past
   - current
   - future
   - considering
   - uncertain

3. evidence/source node 분리
   - search_result
   - user_statement
   - assistant_statement

4. ClaimConflict를 UpdateRequest로 분리
   - 기존 assertion edge의 trust 영구 조정
   - bounded log 기록

5. ClaimAssertion을 WorldGraph에 어떤 형태로 저장할지 결정
```
