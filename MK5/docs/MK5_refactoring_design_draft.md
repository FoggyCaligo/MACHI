# MK5 리팩토링 설계 문서 초안

## 1. 문서 목적

이 문서는 현재 MK5의 파이프라인을 재구성하기 위한 설계 초안이다.
핵심 목적은 다음 네 가지다.

1. 검색과 사고의 순서를 바로잡는다.
2. 현재 입력이 근거처럼 취급되는 문제를 제거한다.
3. `노드가 존재함`과 `질문에 답할 수 있을 정도로 grounding 되어 있음`을 분리한다.
4. 답변 품질 향상을 위해 기능을 덕지덕지 추가하는 대신, 그래프 중심 구조를 단순하고 일관되게 재정렬한다.

이 문서는 구현 세부보다 **구조 원칙과 런타임 흐름**을 먼저 고정하기 위한 문서다.

---

## 2. 현재 구조의 핵심 문제

### 2.1 search와 think의 순서가 뒤바뀌어 있다

현재 파이프라인은 대체로 아래처럼 동작한다.

1. user ingest
2. activation 1차
3. thinking 1차
4. search
5. search ingest
6. activation 2차
7. thinking 2차
8. verbalization

이 구조의 문제는 다음과 같다.

- 검색 전에 이미 결론을 만들기 시작한다.
- 검색이 그래프를 준비하는 전처리가 아니라, 사후 보강이 된다.
- search 결과가 답변에 늦게 반영되거나 충분히 반영되지 않는다.
- think를 두 번 돌리므로 비용과 복잡도가 늘어난다.

### 2.2 질문 구조 분해가 의미 구조가 아니라 표면 조각 수집에 가깝다

현재 입력 분해는 정규식 기반 토큰/블록 추출이 중심이다.
그 결과 다음과 같은 문제가 나온다.

- 자기소개 + 배경설명 + 질문이 한 메시지에 섞이면 질문 초점이 흐려진다.
- `안녕`, `이야`, `편하게`, `지금` 같은 주변 단위가 핵심 후보로 과하게 살아남는다.
- search obligation이 질문 초점이 아니라 표면 단어를 따라간다.

### 2.3 노드 존재와 usable grounding이 구분되지 않는다

현재 구조에서는 어떤 개념이 그래프에 존재하면 direct access가 성공한 것처럼 보일 수 있다.
하지만 실제로는 다음 같은 경우가 있다.

- 사용자 발화 때문에 이름만 생긴 노드
- 검색을 아직 거치지 않은 빈 노드
- 예전에 검색되었지만 최신성이 필요한 노드
- 관련 노드는 있으나 현재 질문의 요구 수준을 충족하지 못하는 노드

즉 `node exists`는 `질문에 답할 수 있다`를 의미하지 않는다.

### 2.4 현재 입력이 근거처럼 보이는 경로가 있다

현재 발화에서 막 생성된 노드는 그래프에 존재하지만, 이것은 근거가 아니다.
현재 입력은 **접근 키**일 뿐이고, grounding 근거가 아니다.

### 2.5 assistant 답변 전체를 다시 그래프에 넣는 경로는 자기 오염 위험이 있다

assistant full answer ingest는 초기에는 “assistant도 그래프를 넓힐 수 있다”는 발상에서 도입되었지만,
현재 철학 기준에서는 오히려 아래 문제가 크다.

- 모델이 말한 문장을 다시 근거처럼 오염시킬 수 있다.
- self-reinforcement가 발생한다.
- 실제 evidence보다 assistant wording이 그래프에 남는다.

---

## 3. 리팩토링 목표

### 3.1 목표 구조

목표 런타임은 아래 순서를 따른다.

1. 입력 수신
2. 입력 분해
3. direct access
4. 부족한 항목 자동 search
5. search 결과 ingest 및 약한 relation 연결
6. local graph build
7. think 1회
8. verbalization
9. assistant snapshot만 저장

즉 핵심은 다음 두 줄이다.

- **search는 think보다 먼저 온다.**
- **think는 답변 가능한 그래프가 준비된 뒤 한 번만 돈다.**

### 3.2 재구성 후 최종 흐름

```text
입력
→ 1차 후보 추출(정규식 기반)
→ LLM 기반 의미 역할 해석
→ 각 의미 단위 direct access
→ usable하지 않은 단위 자동 search
→ search batch ingest
→ 약한 relation 연결
→ local graph build
→ think 1회
→ verbalization
→ assistant snapshot 저장
```

---

## 4. 핵심 설계 원칙

### 4.1 현재 입력은 접근 키이지 근거가 아니다

- 현재 턴에서 생성된 노드는 grounding 근거로 세지 않는다.
- 현재 입력은 어떤 노드를 찾아야 하는지 알려주는 힌트다.
- grounding은 search/document/user-confirmed evidence 등으로 얻는다.

### 4.2 노드 존재와 답변 가능성은 다르다

`direct access 성공`은 더 이상 단순히 `노드가 있다`가 아니다.

성공 조건은 다음과 같다.

- grounded 되어 있다.
- 현재 질문에 충분하다.
- 최신성이 필요한 경우 stale하지 않다.

즉 access 성공 기준은 다음과 같이 바뀐다.

- `node exists`가 아니라
- `node is usable for this question`

### 4.3 mention-only 정책 채택

이 문서는 **안 1**을 채택한다.

즉,

- 노드는 지금처럼 생성될 수 있다.
- 하지만 사용자 발화에서 생긴 이름-only 노드는 `mention-only` 상태를 가진다.
- `mention-only` 노드는 direct access 성공으로 치지 않는다.
- search/document/user-confirmed grounding이 붙어야 비로소 usable node로 본다.

### 4.4 search는 failure fallback이 아니라 graph completion 단계다

search는 “어쩌다 부족하면 덧붙이는 보조”가 아니다.

search는 다음을 수행한다.

- direct access에 실패한 의미 단위를 graph에 채워 넣는다.
- grounded evidence를 생성한다.
- thinking 이전에 graph를 답변 가능한 상태로 만든다.

즉 search는 **pre-think graph completion**이다.

### 4.5 모르면 모른다고 답한다

grounding/search evidence가 없으면, verbalizer는 일반지식으로 빈칸을 메우면 안 된다.
답변 계약은 다음과 같다.

- evidence가 없으면 모른다고 말한다.
- evidence가 부족하면 부족하다고 말한다.
- 추측은 명시적으로 추측이라고 표시하지 않으면 허용되지 않는다.

### 4.6 그래프 저장과 search obligation은 구분한다

모든 normalized concept는 그래프에 들어갈 수 있다.
하지만 모든 concept가 같은 search obligation을 가지는 것은 아니다.

- 그래프 저장은 넓게
- search/direct access obligation은 질문 핵심 단위 중심으로

즉 저장과 답변 책임은 분리한다.

---

## 5. 입력 분해 설계

### 5.1 1차 분해: 정규식 기반 후보 추출

현재처럼 정규식/기계적 방식으로 후보를 넓게 뽑는다.
이 단계의 목적은 가능한 많은 표현을 놓치지 않는 것이다.

예시:

- surface token
- 명사구 후보
- 문장 단위 span

이 단계는 **그래프 저장 후보 생성 단계**다.

### 5.2 2차 분해: LLM 기반 의미 역할 해석

LLM은 새 노드를 많이 생성하는 역할을 맡지 않는다.
LLM이 해야 할 일은, 1차 후보를 읽고 **역할과 중요도와 정보 종류를 라벨링하는 것**이다.

필수 출력은 아래 정도로 제한한다.

- `current_intent`
- `query_focus_span`
- `primary_keywords`
- `secondary_keywords`
- `ignore_for_search`
- `update_needed_labels`

### 5.3 업데이트 필요성 라벨

각 의미 단위는 최소 아래 중 하나의 정보 성격 라벨을 가질 수 있어야 한다.

- `timeless`
  - 거의 안 바뀌는 개념/작품/일반 설명
- `slow_changing`
  - 구조는 있으나 가끔 갱신이 필요한 정보
- `current_state`
  - 최근 상태, 현재 적용 여부, 최신 상황
- `self_or_local`
  - 외부 검색보다 현재 시스템/대화/로컬 그래프를 우선 봐야 하는 것
- `unknown`
  - 불확실, 보수적으로 access/search 판단

이 라벨은 이후 stale 판단과 search 정책의 핵심이 된다.

---

## 6. direct access 설계

### 6.1 direct access 입력

direct access는 `meaning unit` 단위로 수행한다.
각 unit은 최소 아래를 가진다.

- `surface`
- `normalized`
- `importance`
- `update_needed_label`

### 6.2 direct access 결과 상태

각 meaning unit에 대해 access 결과는 아래 중 하나여야 한다.

- `node_missing`
- `node_exists_but_unresolved`
- `node_grounded_and_fresh`
- `node_grounded_but_stale`
- `node_grounded_but_insufficient_for_question`

즉 반환값은 존재 여부가 아니라 **사용 가능 상태**여야 한다.

### 6.3 mention-only 노드 처리

`mention-only` 노드는 다음 성격을 가진다.

- user utterance 때문에 생긴 이름-only 노드
- grounded evidence가 아직 없음
- access 성공으로 치지 않음
- 자동 search 대상이 됨

이 정책으로 “빈 노드가 영원히 남는 문제”를 해결한다.

---

## 7. search 설계

### 7.1 search 트리거 조건

search는 아래 중 하나면 자동으로 실행한다.

- `node_missing`
- `node_exists_but_unresolved`
- `node_grounded_but_stale`
- `node_grounded_but_insufficient_for_question`

즉 search는 direct access 실패의 자동 결과다.

### 7.2 search 대상

search는 **핵심 meaning unit**부터 수행한다.
다만 그래프에는 전체 concept를 저장할 수 있다.

핵심과 비핵심을 나누는 이유는,
그래프 저장과 search obligation을 분리하기 위해서다.

### 7.3 query 방식

- 기본은 개별 concept query
- concept 결합 query는 기본 비활성
- relation-level 보강이 정말 필요할 때만 예외적으로 사용

### 7.4 search ingest

search 결과는 batch ingest 쪽으로 옮긴다.
가능하면 result 하나마다 ingest를 따로 도는 대신,
하나의 search batch 단위로 commit/이벤트를 줄이는 방향을 우선한다.

---

## 8. local graph build / activation 설계

### 8.1 activation 1차 제거

현재의 “search 이전 activation 1차”는 제거 대상으로 본다.
그 역할은 대부분 direct access 단계와 겹친다.

### 8.2 activation은 think 직전에 1회만 수행

activation의 목적은 검색과 direct access가 끝난 뒤,
이미 채워진 그래프를 기반으로 local subgraph를 만드는 것이다.

즉 activation은 다음 조건에서만 돌면 된다.

- direct access 완료
- search completion 완료
- search ingest 완료

### 8.3 중복 block 생성 제거

현재 ingest와 activation이 모두 입력을 다시 segment하는 것은 제거 대상이다.

- 입력 분해 결과는 한 번 만든 뒤 재사용한다.
- activation은 새로 block을 만들지 않고, 기존 meaning unit / seed 결과를 사용한다.

---

## 9. thinking 설계

think는 아래 단계로 1회만 수행한다.

1. contradiction detection
2. trust update
3. structure revision
4. concept differentiation
5. topic following
6. conclusion build

### 9.1 concept differentiation 유지

개념 분화는 유지한다.
이유는 다음과 같다.

- 그래프에 넓게 저장된 개념 중 핵심 개념을 다시 정리하는 역할이 필요하다.
- 질문 초점과 주변 개념을 구분하는 데 도움을 준다.

### 9.2 topic following 유지

주제 따라가기도 유지한다.
이유는 다음과 같다.

- 자기소개 + 배경설명 + 질문이 한 턴에 섞여 있을 때 초점 이동을 추적할 필요가 있다.
- 그래프에 있는 것만 따라가는 것이 아니라, 이번 발화의 질문 clause를 따라가게 해야 한다.

---

## 10. verbalization 설계

### 10.1 verbalization은 grounded contract를 강제해야 한다

verbalizer는 자유 생성기가 아니라, grounded contract를 지키는 레이어여야 한다.

규칙:

- evidence 없음 → 모른다고 답함
- evidence 부족 → 부족하다고 답함
- evidence 있음 → 그 evidence 우선 설명
- snippet보다 passage 우선

### 10.2 hallucination 차단

아래 조건이면 LLM 자유 생성 금지:

- grounded evidence 없음
- search도 안 됨
- boundary response 조건 충족

즉 “모르면 모른다고 답한다”를 코드 레벨에서 강제한다.

---

## 11. assistant answer 저장 정책

### 11.1 full answer ingest 제거

assistant의 자유 생성 문장 전체를 다시 그래프에 넣는 구조는 제거한다.

이유:

- 자기 오염 위험
- self-reinforcement
- 실제 evidence보다 wording이 근거처럼 남음

### 11.2 snapshot만 저장

대신 다음 정도의 lightweight snapshot만 저장한다.

- `topic_terms`
- `tone_hint`
- `answer_goal`
- `response_mode`

즉 assistant state는 남기되, assistant full text는 근거 저장소로 취급하지 않는다.

---

## 12. 제거/축소 대상

### 12.1 제거 대상

- search 이전 think
- activation 1차
- activation 시 재-segmentation
- assistant full answer ingest
- concept 결합 기본 query
- 레거시 scope gate / slot planner / coverage refiner 경로

### 12.2 유지하되 축소 대상

- InputSegmenter: 후보 추출기로 축소
- SearchSidecar: missing concept graph completion 레이어로 재정의
- Verbalizer: grounded contract 강화

---

## 13. 구현 우선순위

### 1단계

- 입력 분해 결과 재사용 구조 도입
- activation 1차 제거
- think 이전 search completion 순서로 pipeline 재배선

### 2단계

- LLM 기반 의미 역할 해석 추가
- update-needed 라벨 추가
- direct access 상태값 확장

### 3단계

- assistant full answer ingest 제거
- snapshot 저장만 남김
- search batch ingest 정리

### 4단계

- verbalizer contract 강화
- hallucination 차단 경계 응답 명시화

---

## 14. 최종 결론

이번 리팩토링의 핵심은 다음 세 줄이다.

1. **현재 입력은 근거가 아니라 접근 키다.**
2. **노드 존재는 access 성공이 아니라, grounded + 충분 + 최신일 때만 access 성공이다.**
3. **search는 think 이후 보강이 아니라, think 이전 graph completion 단계다.**

이 문서는 구현 전에 구조 원칙을 고정하기 위한 초안이다.
다음 단계는 이 문서를 기준으로 실제 파일별 리팩토링 설계서와 작업 순서를 작성하는 것이다.
