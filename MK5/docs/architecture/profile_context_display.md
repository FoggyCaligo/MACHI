# MK5 Profile Context Display / Recall View

작성: 2026-05-18  
상태: 구현 반영 초안

## 핵심 결정

ProfileActivationView 내부에서 Think용 seed와 GraphToLang 노출용 display를 분리한다.

```text
seed_hashes
  Think에 read-only local context로 넣는 내부 활성화 seed

display_hashes
  GraphToLang의 [현재 사용자 맥락]에 직접 노출할 후보
```

즉 어떤 concept은 사고 재료로는 쓰이지만 사용자에게 보이는 기억 후보 목록에는 나오지 않을 수 있다.

## 배경

PR #21 이후 사용자가 직접 말하지 않은 concept이 `사용자 → concept` 임시 edge나 핵심 키워드로 승격되는 문제는 줄었다. 하지만 profile context display에는 여전히 인사말, 저정보량 concept, 먼 과거 후보가 섞일 수 있다.

이번 변경은 문자열 차단 규칙을 쓰지 않고 다음 구조 신호로 display 후보를 고른다.

```text
identity_surface 여부
profile_reference support_count
profile_reference / identity_surface edge_weight
profile/user anchor 밖의 구조 연결도
현재 입력과의 direct overlap 여부
```

현재 입력과 겹쳤다는 사실만으로는 display하지 않는다. overlap은 activation cue가 될 수 있지만, display에는 더 높은 salience가 필요하다.

## identity_surface 처리

동일 endpoint에는 edge가 하나만 존재할 수 있다. 이미 `USER_PROFILE → profile_reference → Concept` edge가 있는 concept이 identity 후보로 재활성화되면 새 edge를 만들지 않고 같은 edge에 `identity_surface` 역할을 추가한다.

이 edge는 여전히 claim이 아니며, 사용자의 확정 identity도 아니다. 의미는 현재 사용자 프로필의 이름/호칭/정체성 표면 후보라는 정도다.

## ProfileRecallView 최소 구조

GraphToLang에는 display context가 있을 때만 다음 섹션을 추가한다.

```text
[ProfileRecallView]
status=active_profile_context
confidence=<profile activation confidence>
display_context=<display labels>
response_contract=...
```

이 구조는 특정 사용자 문장을 문자열로 감지하는 방식이 아니다.

조건은 다음과 같다.

```text
ProfileActivationView 활성
+ display_hashes 존재
→ ProfileRecallView active
```

역할은 LLM이 일반 챗봇 습관으로 기억 부재를 단정하는 것을 줄이고, 현재 사용자 맥락 후보를 근거로 제한적인 기억 범위를 인정하게 하는 것이다. 단, 후보를 확정 사실로 과장하지 않는다.

## 기대 효과

```text
- 핵심 키워드와 사용자 앵커 edge는 direct input 중심으로 유지
- 현재 사용자 맥락 display는 seed보다 보수적으로 노출
- 인사말/저정보량 concept의 display 노출 감소
- profile context가 있을 때 기억 응답 안정성 개선
```

## 다음 작업

```text
1. 실제 로컬 DB에서 display_hashes 결과 확인
2. display threshold / support / structural_context 기준 조정
3. SearchNeed primitive 추가
4. ProfileRecallView를 prompt section이 아니라 별도 ConclusionView 계층으로 승격
5. USER_PERSON::<surface> identity layer 추가
```

