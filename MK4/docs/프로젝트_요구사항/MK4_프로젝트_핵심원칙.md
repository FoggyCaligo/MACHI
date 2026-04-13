# MK4 프로젝트의 방향성 / 철학 / 규정 / 장기 유지 원칙

이 문서는 MK4에서 앞으로도 유지되어야 하고, 쉽게 바뀌지 않을 핵심 방향과 철학만 정리한 문서다.

## 1. 프로젝트의 정체성

MK4는 답변을 잘하는 챗봇보다,
시간이 지날수록 더 일관되게 사용자를 이해하는 로컬 개인화 인지 시스템을 목표로 한다.

핵심은 다음과 같다.

- 단순한 fact 저장보다 user model 형성이 우선이다.
- 기억은 append-only 로그가 아니다.
- correction으로 언제든 재구성될 수 있어야 한다.
- prompt로 성격을 강하게 박는 것이 아니라, memory-driven personalization을 지향한다.
- 일반 채팅, 첨부 텍스트, ZIP artifact, project 입력은 모두 evidence-first로 다뤄야 한다.

MACHI 전체 맥락에서 보면, MK4는 독립된 챗봇 프로젝트가 아니라
**개인 전용 Cognitive Partner / 개인 인지 시스템 비전에서 memory substrate를 구현하는 현재 작업 축**이다.

즉 MK4는:
- MK1의 Cognitive Partner / 구조 학습 / 자아-세계-기억 분리 문제의식
- MK2의 운영 규칙 / 승인 / 거버넌스 문제의식
- MK3의 local agent / trusted search / light memory 프로토타입

위에 이어지는 단계이며,
현재는 특히 **evidence-first / correction-first / revisable memory**를 실제 구조와 코드로 구현하는 역할을 맡는다.

또한 상위 MACHI 철학과 연결되는 다음 원칙을 항상 같이 본다.
- structure before comfort
- verification before performance
- memory is revisable
- the user remains the decision owner

## 2. 구조 철학

### 2-1. topic과 project_id는 다른 축이다
- topic은 의미 축이다.
- project_id는 출처 축이다.
- 둘은 대체 관계가 아니다.

### 2-2. 입력 채널이 달라도 공통 기억 구조로 수렴해야 한다
입력 채널:
- 일반 채팅
- 첨부 텍스트
- ZIP artifact
- project 질문
- correction 입력

이 채널들은 다르더라도 결국 아래 공통 기억 의미론으로 수렴해야 한다.

- general
- candidate
- confirmed

### 2-3. evidence-first
원문을 곧바로 profile로 확정하지 않는다.

기본 구조:
입력 → evidence → tier 배정 → 저장/승격 → 다음 턴 재사용

## 3. 기억 정책

### 3-1. tier 의미론
- general: 저장 가치는 있지만 기본 응답에 주입하지 않는 정보
- candidate: 승격 후보
- confirmed: 현재 모델이 보고 있는 사용자상

### 3-2. confirmed는 절대 진실이 아니다
- confirmed도 correction으로 깨질 수 있다.
- confirmed는 현재 시점의 가설적 사용자상이다.

### 3-3. general은 넓게 저장한다
- general은 버리는 층이 아니라 장기적으로 general → candidate로 올라갈 수 있는 재료층이다.
- 다만 기본 응답 주입은 하지 않는다.

### 3-4. promotion 정책
- 같은 의미 evidence가 2회 반복되면 승격 가능
- 1회라도 매우 높은 신뢰도면 승격 가능
- direct confirm은 채널 공통 기준
- 채널 간 교차 evidence도 승격 근거로 허용

## 4. 금지 원칙

### 4-1. assistant 발화는 profile tier 재료 금지
assistant가 생성한 문장은:
- general
- candidate
- confirmed

어떤 profile tier의 재료로도 쓰면 안 된다.

assistant 발화는 허용된다면:
- raw log
- 디버깅용 기록
- recent conversation 요약 재료
정도에만 제한적으로 남길 수 있다.

### 4-2. 문자열 의미 해석 하드코딩 금지
- 특정 키워드 포함 여부로 사용자 성향, 정정, 선호, NEED를 해석하지 않는다.
- 규칙 기반 키워드 매칭, 임의의 의미 추정용 문자열 비교는 레거시로 본다.
- route 결정, tool 사용 여부, 사용자 이해, correction 의도 판별을 문자열 if문으로 처리하지 않는다.
- "임시 우회"라는 이유로 surface pattern 휴리스틱을 의미 판단 계층에 다시 넣지 않는다.

### 4-3. 실패 숨기기 금지
- 오류는 오류처럼 드러나야 한다.
- fallback으로 실패를 감추지 않는다.
- 지금 단계에서는 하드코딩된 임시 보정보다, 명확한 실패가 낫다.

### 4-4. 보조 레이어가 본체 계약을 우회하면 안 된다
- tool, guard, fallback, helper는 응답 생성 본체를 대체하지 않는다.
- 일반 응답 경로의 timeout / truncation / continuation / honesty 계약은 공용 runner 위에서 유지한다.
- 보조 레이어는 필요할 때만 개입하고, no-op일 때는 본체 경로를 그대로 통과시킨다.

## 5. 프롬프트 철학

- 프롬프트는 길이보다 계약이 중요하다.
- 장황한 설명보다 역할, 판단 기준, 출력 스키마를 짧게 유지한다.
- 모델 성격을 과하게 강제하기보다, 태스크 경계와 출력 형식을 명확히 하는 데 집중한다.
- recent conversation은 raw transcript보다 요약을 우선한다.
- 첨부 텍스트 분석에서는 원문 재낭독보다 분석 결과를 우선한다.

## 6. retrieval 철학

장기 방향은 의미 기반 retrieval 통일이다.

즉:
- topic routing
- profile recall
- response context retrieval
- project retrieval

이 계층들이 가능한 한 같은 retrieval 철학 위에서 움직여야 한다.

지금 단계에서는 완전히 통일되지 않았더라도,
장기 방향은 문자열 기반보다 의미 기반에 있다.

## 7. correction 철학

- correction은 부가기능이 아니라 핵심 메커니즘이다.
- 잘못 형성된 profile은 언제든 correction으로 깨지고 다시 구성될 수 있어야 한다.
- 오염을 "처음부터 아무 것도 안 저장하는 것"으로 막기보다,
  나중에 다시 고칠 수 있는 구조로 풀어야 한다.

## 8. 앞으로 쉽게 바뀌지 않을 우선순위

1. 일반 채팅을 첨부/프로젝트 수준으로 끌어올리기
2. general / candidate / confirmed를 전 채널에서 같은 기준으로 맞추기
3. 그 다음 공통 ingress/apply를 더 엄밀하게 정리하기
4. retrieval 철학을 장기적으로 통일하기

## 9. 한 줄 요약

MK4는 "지금 한 번 잘 말하는 모델"보다,
"시간이 지날수록 더 일관되게 사용자를 이해하고,
틀리면 다시 고칠 수 있는 로컬 인지 시스템"을 지향한다.
