# MK5 현재 구조 ↔ 목표 구조 대응 설계표

## 문서 목적

이 문서는 **현재 sync된 MK5 코드의 실제 실행 순서**와, 앞으로 지향할 **목표 구조**를 1:1로 대응시켜 정리한 설계표다.

핵심 목적은 다음과 같다.

- 현재 파이프라인에서 **어디가 철학과 어긋나는지**를 명확히 한다.
- 목표 구조로 가기 위해 **무엇을 삭제/병합/이동**해야 하는지 정리한다.
- 이후 리팩토링을 할 때 **단계별 구현 기준표**로 쓴다.

---

## 전제 철학

이 설계표는 아래 철학을 기준으로 한다.

1. **현재 입력은 접근 키이지 근거가 아니다.**
2. **노드 존재는 access 성공이 아니다.**
3. **access 성공 조건은 `usable grounding`이다.**
4. **검색은 think 이전에 완료되어야 한다.**
5. **그래프는 대답 가능한 상태로 먼저 채워지고, 그 다음 think가 돌아야 한다.**
6. **assistant의 자유 생성 답변은 그래프의 근거가 아니다.**
7. **모르면 모른다고 답해야 하며, 근거 없는 일반지식 보충은 금지한다.**
8. **안 1 채택:** mention-only 노드는 허용하되, access 성공으로 치지 않는다.

---

## 현재 구조 요약

현재 sync된 코드 기준 실제 순서는 아래와 같다.

```text
/chat 요청
→ ChatPipelineRequest 생성
→ user ingest
→ activation 1차
→ thinking 1차
→ search need 판단
→ 필요 시 search
→ search ingest
→ activation 2차
→ thinking 2차
→ search decision 재평가
→ search_context attach
→ verbalization
→ assistant answer ingest
→ debug payload 생성
→ JSON 반환
```

### 현재 구조의 핵심 문제

- **search가 think보다 뒤에 있다.**
- **입력을 두 번 분해한다.**
- **activation이 두 번 돈다.**
- **thinking이 두 번 돈다.**
- **assistant answer를 다시 그래프에 ingest한다.**
- **현재 입력에서 생성된 노드와 grounded 노드의 구분이 구조적으로 약하다.**
- **입력 분해가 정규식 중심이라 질문 초점 분해력이 낮다.**

---

## 목표 구조 요약

앞으로 지향할 목표 구조는 아래와 같다.

```text
1. 입력 수신
2. 정규식 기반 후보 분해
3. LLM이 후보들을 읽고 의미 역할/핵심도/업데이트 필요성 라벨링
4. 각 meaning unit direct access
5. usable하지 않은 unit 자동 search
6. search result batch ingest
7. 약한 relation 연결
8. local graph build (activation 1회)
9. think 1회
   - contradiction
   - trust
   - revision
   - concept differentiation
   - topic following
   - conclusion
10. verbalization
11. assistant snapshot만 저장 (full answer ingest 없음)
```

### 목표 구조의 핵심 원칙

- **search-before-think**
- **입력 분해 1회**
- **activation 1회**
- **thinking 1회**
- **assistant full answer ingest 제거**
- **검색 결과는 그래프를 채우는 전처리**
- **LLM은 의미 후보를 대량 생성하지 않고, 기존 후보를 해석/라벨링**

---

## 현재 구조 ↔ 목표 구조 대응표

| 현재 단계 | 현재 코드의 역할 | 목표 단계 | 목표 역할 | 조치 |
|---|---|---|---|---|
| user ingest 전 API 파싱 | HTTP 요청 해석 | 입력 수신 | 동일 | 유지 |
| `InputSegmenter.segment()` in ingest | 정규식 기반 block 생성 | 정규식 기반 후보 분해 | 넓게 후보 추출 | 유지하되 출력 의미를 `candidate`로 재정의 |
| 없음 | 없음 | LLM 의미 라벨링 | 후보들에 역할/핵심도/업데이트 필요성 라벨 부여 | **신규 단계 추가** |
| `DirectNodeAccessor.resolve()` in ingest | address hash 기반 direct access | direct access | 동일 | 유지 |
| ingest 중 노드 생성 | mention-only 포함 생성 | mention-only / grounded 구분 생성 | 노드는 만들되 usable 여부 분리 | 유지하되 상태 모델 강화 |
| activation 1차 | 현재 입력 기반 seed/local graph 구축 | 삭제 또는 pre-think graph build로 흡수 | direct access/search 이후 1회 activation | **삭제/병합** |
| thinking 1차 | search 전 임시 사고 | 제거 | think는 search 이후 1회만 | **삭제** |
| search need 판단 | activation/thinking 이후 필요성 판정 | usable grounding 판정 | meaning unit 단위 access 결과로 search 결정 | **앞으로 이동** |
| search | 후처리 보강 | 자동 search | direct access 실패 unit 보강 | 유지하되 위치 이동 |
| result별 search ingest | 검색 결과를 개별 ingest | batch ingest | 검색 결과를 묶어서 ingest | **병합** |
| activation 2차 | search 후 local graph 재구축 | activation 1회 | 최종 graph build | 현재 activation 2차를 본체로 승격 |
| thinking 2차 | search 후 재사고 | think 1회 | 최종 사고 | 현재 thinking 2차를 본체로 승격 |
| search decision 재평가 | post-search grounding 재평가 | think 이전 access 판정 또는 search 후 1회 확인 | search 성공 여부 최종 확인 | 유지하되 단순화 |
| search_context attach | verbalization용 상태 부착 | 동일 | evidence/grounding 상태 전달 | 유지 |
| verbalization | 답변 생성 | 동일 | grounded evidence 우선 답변 | 유지하되 계약 강화 |
| assistant answer ingest | assistant 응답을 그래프에 다시 적재 | assistant snapshot 저장 | topic/tone/intent snapshot만 저장 | **full ingest 제거** |
| debug payload 생성 | 디버그 출력 | 동일 | 유지 | 유지 |

---

## 단계별 상세 설계

### 0. 입력 분해에 LLM 사용

#### 현재
- `InputSegmenter`가 정규식 기반으로 block을 만든다.
- 질문 핵심이 아니라 표면 단어 조각이 많이 살아남는다.

#### 목표
- 정규식 기반으로 **후보를 넓게 추출**한다.
- 그 후 LLM이 후보들을 순서대로 읽고, 아래 라벨을 붙인다.

#### LLM 출력 목표
- `current_intent`
- `primary_units`
- `secondary_units`
- `ignore_for_search`
- `update_class`

#### update_class 예시
- `timeless`
- `slow_changing`
- `current_state`
- `self_or_local`
- `unknown`

#### 중요 원칙
- LLM은 **새 의미 단위를 대량 생성하지 않는다.**
- LLM은 **이미 뽑힌 후보를 해석/라벨링만 한다.**
- 문장 전체를 별도 노드로 만들지 않는다.

---

### 1. direct access와 usable grounding

#### 현재
- 노드가 있으면 접근 성공처럼 보이기 쉽다.

#### 목표
- 노드 존재와 access 성공을 분리한다.

#### access 상태 모델
- `node_missing`
- `mention_only`
- `grounded_and_fresh`
- `grounded_but_stale`
- `grounded_but_insufficient`

#### 안 1 채택
- mention-only 노드는 허용한다.
- 하지만 **access 성공으로 치지 않는다.**

즉 access 성공 조건은:

> `node exists`가 아니라, `node is usable for this question`

---

### 2. search-before-think

#### 현재
- think가 먼저 돌고 search가 나중에 돈다.
- search 결과가 같은 턴 사고에 약하게 반영된다.

#### 목표
- search는 think 이전의 **graph completion 단계**다.

#### 원칙
- direct access 실패한 meaning unit은 **자동 search**로 빠진다.
- 단, 실패 기준은 노드 부재가 아니라 **usable grounding 실패**다.

즉 아래 경우 모두 search 트리거 대상이다.
- 노드 없음
- mention-only 노드
- grounded지만 stale
- grounded지만 현재 질문에 insufficient

---

### 3. query 생성 기능 분리

#### 현재
- search query 생성이 search need 판단과 강하게 얽혀 있다.

#### 목표
- query 생성은 think 바깥, graph completion 단계의 일부가 된다.

#### 원칙
- **개념 결합은 기본적으로 하지 않는다.**
- meaning unit별 **개별 query**만 발행한다.
- relation 검색은 예외적 2차 보강으로만 둔다.

---

### 4. activation 1차 삭제 / activation 2차 승격

#### 현재
- activation이 두 번 돈다.
- 1차 activation은 search 이전 임시 local graph를 만든다.

#### 목표
- activation은 **search 이후 한 번만** 돈다.

#### 조치
- 현재 activation 1차는 삭제 또는 pre-think access 단계에 흡수
- 현재 activation 2차를 최종 activation 본체로 사용

---

### 5. thinking 1차 삭제 / thinking 2차 승격

#### 현재
- thinking이 두 번 돈다.
- search 전 임시 결론과 search 후 결론이 섞인다.

#### 목표
- think는 **최종 graph가 준비된 뒤 한 번만** 돈다.

#### think 내부 유지 요소
- contradiction
- trust
- revision
- concept differentiation
- topic following
- conclusion

즉 현재의 thinking 2차를 본체로 승격하고, thinking 1차는 제거한다.

---

### 6. assistant answer ingest 제거

#### 현재
- assistant의 자유 생성 답변을 다시 graph ingest한다.

#### 문제
- self-reinforcement 위험
- assistant가 말한 문장이 근거처럼 오염될 수 있음
- 그래프 충돌 갱신이 실제 evidence보다 assistant 문장에 끌릴 수 있음

#### 목표
- assistant full answer ingest 제거
- 대신 lightweight snapshot만 저장

#### 남길 snapshot 예시
- `topic_terms`
- `tone_hint`
- `answer_goal`
- `response_mode`

즉 assistant는 **그래프 근거 source**가 아니라, **대화 운영 snapshot source**로 다룬다.

---

## 병목 / 철학 어긋남 체크리스트

### 병목
- 입력을 두 번 segmentation
- activation 두 번
- thinking 두 번
- search result 개별 ingest 반복
- assistant answer 재ingest

### 철학 어긋남
- search가 think 뒤에 있음
- 현재 입력과 grounded evidence 구분 약함
- 노드 존재를 access 성공처럼 보기 쉬움
- assistant 문장이 그래프를 오염시킬 수 있음
- LLM이 근거 없이 일반지식으로 빈칸을 메울 위험

---

## 구현 우선순위

### 1차 리팩토링
1. assistant answer ingest 제거
2. activation 1차 제거
3. thinking 1차 제거
4. search를 think 앞으로 이동
5. current input segmentation 1회로 통합

### 2차 리팩토링
6. LLM 의미 라벨링 단계 추가
7. access 상태 모델(`mention_only`, `stale`, `insufficient`) 도입
8. batch search ingest 도입
9. verbalizer grounded contract 강화

### 3차 리팩토링
10. relation-level 보강 검색
11. snapshot 저장 구조 정리
12. 문서/테스트 전면 동기화

---

## 최종 목표 구조

```text
1. 입력 수신
2. 정규식 기반 후보 분해
3. LLM 후보 라벨링
   - 핵심도
   - 역할
   - 업데이트 필요성
4. 각 meaning unit direct access
5. usable하지 않은 unit 자동 search
6. search result batch ingest
7. 약한 relation 연결
8. local graph build (activation 1회)
9. think 1회
10. verbalization
11. assistant snapshot 저장
12. debug / response 반환
```

---

## 이 문서를 기준으로 다음 단계에서 해야 할 것

다음 단계는 이 설계표를 코드 변경 계획으로 내리는 것이다.

즉 아래 세 문서를 추가로 만들면 된다.

1. **파일 단위 변경 계획서**
   - 어느 파일을 지우고
   - 어느 파일을 수정하고
   - 어느 파일에 어떤 책임을 넣을지

2. **데이터 모델 변경 계획서**
   - mention-only / grounded / stale / insufficient 상태를 어디에 저장할지

3. **테스트 재작성 계획서**
   - 현재 테스트 중 무엇을 버리고
   - 무엇을 새로 써야 하는지

