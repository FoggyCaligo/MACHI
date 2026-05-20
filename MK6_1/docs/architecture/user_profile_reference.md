# MK6 UserProfile Reference 정책

작성: 2026-05-18  
상태: skeleton 정책 v1  
범위: 현재 사용자 프로필을 개인화된 concept reference index로 사용하는 구조

---

## 1. 핵심 결정

UserProfile은 사용자에 대한 사실 저장소가 아니다.

> UserProfile은 현재 사용자와의 대화에서 등장한 WorldGraph concept들을 참조하는 개인화된 context index다.

즉 개념 자체는 기존 흐름대로 TempThoughtGraph와 WorldGraph에 존재한다.

```text
사용자 발화
  → TempThoughtGraph
  → WorldGraph concept / edge
```

그리고 별도로 현재 사용자 프로필은 해당 concept들을 참조한다.

```text
ANCHOR_USER
  → current_profile
  → USER_PROFILE::<anchor>

USER_PROFILE::<anchor>
  → profile_reference
  → Concept
```

---

## 2. 세 단계 구조

사용자 발화 처리의 기본 흐름은 다음과 같다.

```text
1. 사용자 파악
   - ANCHOR_USER

2. 사용자 프로필 접근
   - 없으면 USER_PROFILE 생성
   - ANCHOR_USER → current_profile → USER_PROFILE

3. 대화에서 나온 concept들을 현재 사용자 프로필에 참조 연결
   - 개념은 WorldGraph에 둔다
   - UserProfile에는 concept node reference edge만 둔다
```

---

## 3. profile_reference edge의 의미

`profile_reference`는 claim/fact가 아니다.

```text
USER_PROFILE → profile_reference → 개발자
```

이 edge는 다음을 의미한다.

```text
이 사용자의 대화/기억 맥락에서 개발자 concept이 등장했다.
```

다음을 의미하지 않는다.

```text
사용자는 개발자다.
```

사용자가 개발자라는 주장은 별도 ClaimAssertion으로 표현되어야 한다.

---

## 4. ProfileActivationView

UserProfile을 만든 것만으로는 현재 턴의 Think가 사용자 맥락을 자동으로 쓰지 않는다.

따라서 Update/Context 준비 단계에서 `ProfileActivationView`를 만든다.

```text
ProfileActivationView
  - profile_hash
  - reference_hashes
  - matched_hashes
  - seed_hashes
  - seed_scores
  - confidence
  - activation_reason
```

동작 원칙:

```text
1. UserProfile은 항상 보장한다.
2. profile_reference 전체를 항상 활성화하지 않는다.
3. 현재 입력 concept과 profile_reference target이 겹칠 때만 활성화한다.
4. 활성화되면 seed_hashes의 local subgraph를 Think에 read-only context로 로드한다.
5. GraphToLang에는 profile_reference edge가 아니라 활성화된 concept label 요약만 제공한다.
6. seed 선정은 문자열 차단 목록이 아니라 support_count, edge_weight, 구조 연결도, current overlap으로 정제한다.
```

예:

```text
현재 입력: 난 신재용이라고 해. 날 기억하니?
프로필 참조: 신재용, 개발자, 기획자, MK6
입력/프로필 overlap: 신재용

→ ProfileActivationView 활성화
→ 신재용 및 주요 profile reference concept local subgraph 로드
→ GraphToLang [현재 사용자 맥락]에 concept label 요약 제공
```

---

## 5. Profile context 정제 기준

`profile_reference`는 대화에서 등장한 모든 concept을 연결하므로, 그대로 노출하면 인사말/어미/저정보량 concept이 섞일 수 있다.

따라서 GraphToLang에 들어가는 `[현재 사용자 맥락]`은 다음 구조 점수로 정제한다.

```text
profile context score
  = current input overlap bonus
  + profile_reference support_count
  + profile_reference edge_weight
  + profile/user anchor 밖의 구조 연결도
```

금지하는 방식:

```text
- 특정 문자열을 하드코딩해 제거
- '안녕', '이라', '있구나' 같은 surface form 직접 차단
```

허용하는 방식:

```text
- 현재 입력과 profile reference의 overlap 여부
- 해당 concept의 profile_reference support_count
- 해당 concept이 profile/user anchor 밖에서 가진 non-profile edge 수
- edge_weight / trust 계열 점수
```

이 기준은 완성된 ontology가 아니라, profile context 노이즈를 줄이기 위한 임시 salience gate다.

---

## 6. 사용자 identity surface binding

`USER_PROFILE → profile_reference → Concept`는 사실/정체성 주장이 아니다. 따라서 이름/호칭/정체성 후보는 별도 edge로 누적한다.

```text
USER_PROFILE
  → identity_surface
  → Concept
```

`identity_surface`는 다음을 의미한다.

```text
이 concept은 현재 사용자 프로필의 이름/호칭/정체성 표면 후보다.
```

다음을 의미하지 않는다.

```text
사용자와 해당 concept이 완전히 동일한 존재로 확정되었다.
```

초기 skeleton에서는 문자열 패턴으로 이름을 추측하지 않는다. 대신 다음처럼 보수적으로 승격한다.

```text
1. concept이 이미 USER_PROFILE의 profile_reference에 존재한다.
2. 현재 입력 concept과 profile_reference target이 겹쳐 ProfileActivationView.matched_hashes에 들어온다.
3. 이 matched concept을 identity_surface 후보로 연결/강화한다.
```

즉 최초 등장 concept은 보통 `profile_reference`에 머물고, 반복/재활성화된 concept이 identity 후보로 올라간다.

---

## 7. 사용자 앵커 임시 edge weight

`ANCHOR_USER → Concept` 임시 edge는 claim이 아니다. 이 edge는 현재 턴에서 사용자가 해당 concept을 발화했다는 관측/활성화 view다.

다만 사용자 발화 주체와 concept의 연결은 일반 co-occurrence보다 중요하므로, 기본 weight를 분리한다.

```text
ANCHOR_USER → Concept temporary edge: 1.35
Goal → Concept temporary edge: 0.85
기타 anchor temporary edge: 1.0
```

이 weight는 사용자 identity 확정 신뢰도가 아니다. identity 확정/후보 누적은 `identity_surface`와 향후 `USER_PERSON::<surface>` 계층에서 담당한다.

---

## 8. ClaimAssertion subject binding 1차

사용자 발화에서 생성되는 ClaimAssertion은 source가 사용자다.

```text
ClaimAssertion.source = ANCHOR_USER
```

subject는 아직 완전한 의미 분석이 아니므로 다음 순서로 잡는다.

```text
1. ProfileActivationView.matched_hashes가 있으면 해당 concept을 subject 후보로 사용
2. 없으면 현재 입력 graph의 concept projection을 임시 subject로 사용
```

이 구조는 self-claim 전용 그래프가 아니다. 일반 ClaimAssertion의 subject binding을 UserProfile identity 후보와 연결하는 1차 skeleton이다.

---

## 9. 왜 이 구조가 필요한가

이 구조는 다음 문제를 줄인다.

```text
1. 사용자와 관련된 concept space를 빠르게 재활성화할 수 있다.
2. 사용자 자기정보와 외부 세계지식을 섞지 않는다.
3. 동명이인/동일 surface form 문제에서 사용자별 맥락을 분리할 수 있다.
4. SelfClaimGraph 같은 케이스별 그래프를 만들 필요가 줄어든다.
5. 현재 사용자 맥락을 Think에 넘기되, 내부 profile edge가 언어화로 새는 것을 막는다.
```

---

## 10. GraphToLang 노출 규칙

UserProfile 자체와 profile_reference edge는 내부 구조다.

따라서 GraphToLang은 다음을 일반 응답 근거로 노출하지 않는다.

```text
- USER_PROFILE node
- ANCHOR_USER → current_profile edge
- USER_PROFILE → profile_reference → Concept edge
```

대신 ProfileActivationView가 활성화된 경우에만 다음 섹션을 제공한다.

```text
[현재 사용자 맥락]
신재용, 개발자, 기획자, MK6
```

단, 이는 확정된 사용자 사실 목록이 아니라 현재 사용자 프로필에서 재활성화된 concept 후보들이다.

---

## 11. TODO

```text
1. UserProfile reference edge의 salience/decay 정책 추가
2. 반복 등장 concept의 support_count/edge_weight 조정 정책 개선
3. profile activation cue를 overlap 외 구조로 확장
4. USER_PERSON::<surface> identity binding 추가
5. ClaimAssertion relation/object/temporal_scope 고도화
6. ProfileActivationView를 activation score에 더 정교하게 반영
7. 핵심 키워드/참고 개념 선정도 ConclusionGraph 기반으로 이전
```
