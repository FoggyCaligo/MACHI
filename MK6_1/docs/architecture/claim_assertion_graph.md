# MK6 Claim / Assertion Graph

작성: 2026-08-01  
상태: active  
범위: 사용자 발화, assistant 발화, 검색 결과, 정정/충돌을 케이스별 전용 그래프가 아니라 일반 assertion 구조로 처리

---

## 1. 핵심 원칙

MK6_1은 다음 같은 전용 그래프 타입을 늘리지 않습니다.

- `SelfClaimGraph`
- `CorrectionGraph`
- `PreferenceGraph`
- `PlanGraph`

대신 모든 발화를 먼저 일반 `ClaimAssertion`으로 투영합니다.

```text
ClaimAssertion
  - source
  - subject
  - object
  - provenance
  - temporal_scope
  - confidence
```

정정도 별도 그래프 타입이 아니라,

```text
current ClaimAssertion
  <-> conflict / replacement
previous AssertionState
```

로 해석합니다.

---

## 2. 주요 primitive

### `ClaimAssertion`

한 번의 발화나 결과 묶음에서 추출된 일반 주장 단위입니다.

### `AssertionState`

직전 응답 또는 현재 턴의 주장 상태 projection입니다.

- key/ref hash
- selected graph
- assertion 목록
- 관련 edge id

### `ClaimConflict`

현재 assertion과 이전 assertion state 사이의 conflict 후보입니다.

### `ConclusionGraph`

GraphToLang에 넘길 수 있도록 answer path 또는 conflict path를 묶은 projection입니다.

---

## 3. 사용자 자기서술 처리

자기서술은 별도 `SelfClaimGraph`를 만들지 않습니다.

예:

```text
난 재용이야
26살이야
프론트엔드 개발자야
```

이런 발화는 모두 일반 user assertion으로 들어갑니다.

```text
source = user
provenance = user_statement
subject = 현재 사용자와 bind된 concept
object = 현재 입력에서 확인된 concept
```

subject binding은 문자열 휴리스틱이 아니라 아래 구조를 사용합니다.

- `ProfileActivationView`
- `profile_reference`
- `identity_surface`
- 현재 입력 direct concept

즉 이름 텍스트 자체를 규칙으로 박지 않고, 현재 세션의 사용자 프로필 문맥과 입력 그래프의 구조적 겹침으로 binding합니다.

---

## 4. 정정 처리

정정도 별도 `CorrectionGraph`를 만들지 않습니다.

현재 구현의 핵심은 문자열 cue가 아니라 **assertion replacement** 입니다.

### 이전 방식에서 피하는 것

- `"아니야"`, `"정정"` 같은 단어 매칭
- 이름 하드코딩
- 문장 패턴 전용 규칙

### 현재 방식

1. 현재 user assertion의 subject/object를 만든다.
2. 직전 assistant assertion state를 본다.
3. 같은 subject에 대해,
4. 이전 object와 다른 새 object가 들어오면,
5. 이전 object를 "대체된 대상"으로 본다.

그 결과:

- 새 object 방향으로 `user_assertion` edge 강화
- 이전 object 방향으로 `user_correction_conflict` edge 생성/강화
- 이전 assertion edge에는 `conflict_count`, `contradiction_pressure` 반영

즉 정정 여부는 문장의 단어가 아니라,

```text
같은 subject
+ 새 object 도입
+ 이전 object 대체
```

라는 구조적 변화로 판단합니다.

### 한계

현재 구조는 "부정만 있고 대체 object가 전혀 없는 입력"에는 보수적으로 동작합니다.

예:

```text
나는 의사가 아니야
```

이 경우는 새 object가 없으므로 replacement 신호가 약합니다.  
반대로,

```text
나는 의사가 아니고 개발자야
```

처럼 새 object가 함께 들어오면 정정 구조를 더 안정적으로 잡을 수 있습니다.

---

## 5. ClaimConflict와 ConclusionGraph

`ConclusionGraph`는 더 이상 `graph_kind="correction"` 같은 케이스 타입을 갖지 않습니다.

충돌 구조는 아래로 판단합니다.

```text
ConclusionGraph.has_conflict_structure
  = conflict_paths 또는 exception_hashes 존재 여부
```

GraphToLang도 `graph_kind`가 아니라 실제 conflict path를 보고 응답을 조직합니다.

---

## 6. 검색 결과와 assertion

검색 결과는 이제 텍스트 부록이 아니라 그래프 입력입니다.

- 검색 결과 텍스트를 다시 `lang_to_graph()`에 통과
- 결과 노드/에지를 `search` provenance로 생성 또는 재사용
- 현재 로컬 그래프와 bridge edge로 연결
- 필요 시 결론 그래프와 별도로 `search_graph` 섹션으로 전달

이 구조는 claim/assertion 흐름과 충돌하지 않습니다.  
검색에서 들어온 근거는 `external` speaker 맥락으로 분리되고, user assertion이나 assistant assertion과 구분됩니다.

---

## 7. 금지 규칙

1. `SelfClaimGraph`를 다시 만들지 않는다.
2. `CorrectionGraph`를 다시 만들지 않는다.
3. 이름 문자열을 하드코딩하지 않는다.
4. 정정 여부를 문자열 패턴으로 판단하지 않는다.
5. 사용자 프로필을 사실 저장소 그 자체로 다루지 않는다.

---

## 8. 남은 TODO

1. subject binding 고도화
   - `ANCHOR_USER`
   - `USER_PROFILE`
   - surface alias 정규화

2. temporal/state scope 확장
   - past
   - current
   - future
   - uncertain

3. evidence/source 분리 강화
   - user
   - assistant
   - search
   - system

4. replacement 기반 정정에서 relation predicate 대응 범위 확장
   - 같은 subject의 다중 속성
   - 직업/나이/소속/지역 등 범주 차이

5. ClaimAssertion의 장기 world persistence 정책 정교화
