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

## 4. 왜 이 구조가 필요한가

이 구조는 다음 문제를 줄인다.

```text
1. 사용자와 관련된 concept space를 빠르게 재활성화할 수 있다.
2. 사용자 자기정보와 외부 세계지식을 섞지 않는다.
3. 동명이인/동일 surface form 문제에서 사용자별 맥락을 분리할 수 있다.
4. SelfClaimGraph 같은 케이스별 그래프를 만들 필요가 줄어든다.
```

---

## 5. GraphToLang 노출 규칙

UserProfile 자체와 profile_reference edge는 내부 구조다.

따라서 GraphToLang은 다음을 일반 응답 근거로 노출하지 않는다.

```text
- USER_PROFILE node
- ANCHOR_USER → current_profile edge
- USER_PROFILE → profile_reference → Concept edge
```

단, UserProfile이 참조하는 Concept 자체는 일반 WorldGraph concept이므로 다른 경로에서 결론 구조에 포함될 수 있다.

---

## 6. TODO

```text
1. UserProfile reference edge의 salience/decay 정책 추가
2. 반복 등장 concept의 support_count/edge_weight 조정 정책 개선
3. profile reference를 local activation seed로 사용할지 결정
4. USER_PERSON::<surface> identity binding 추가
5. ClaimAssertion subject binding과 UserProfile 연결
```
