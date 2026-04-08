# MK4 핸드오프 요약본 (다음 채팅 이어받기용)

이 문서는 2026-04-08 기준 MK4의 현재 상태, 최근 작업 내용, 남은 과제를 다음 채팅에서 바로 이어갈 수 있도록 요약한 문서다.

---

## 0. 프로젝트 한 줄 정의

MK4는 **사용자와의 대화 및 산출물을 근거로, 시간이 지날수록 더 정확해지는 사용자 모델을 구축하는 로컬 개인화 인지 시스템**이다.
핵심은 "답변 잘하는 챗봇"이 아니라, **사용자 이해의 일관성과 갱신 가능성**이다.

---

## 1. 현재 작업 원칙

중요:
- 기준 작업본은 업로드된 ZIP이 아니라 **assistant 로컬 작업 폴더**다.
- 현재 기준 작업 폴더:
  - `/mnt/data/mk4_work/MK4`
- 사용자가 새 ZIP을 주면,
  - 그 ZIP을 기준으로 새로 작업하는 것이 아니라,
  - 현재 작업본과의 **차이만 동기화**하는 방식으로 이어간다.

응답 형식 선호:
- 코드 수정은 `파일 위치 + 파일 전체 코드` 또는 `파일 경로 + 다운로드 링크`
- 긴 파일은 다운로드 링크 방식 허용

---

## 2. 큰 철학 / 설계 방향

### 핵심 철학
1. memory is not append-only
   - 기억은 단순 누적이 아니라 update / consolidate / compress / discard 가능해야 한다.

2. fact 저장보다 user model 형성이 우선
   - 무엇을 말했는지보다,
     - 어떤 사고방식인지
     - 무엇을 NEED로 느끼는지
     - 어떤 설명 방식을 선호하는지
     - 최근 correction이 무엇인지
     를 구조화하는 것이 핵심이다.

3. artifact -> evidence -> candidate -> confirmed profile
   - 문서/ZIP/블로그/회고는 곧바로 profile이 아니다.
   - evidence를 뽑고, candidate로 두고, 충분히 검증되면 confirmed profile로 승격한다.

4. correction은 부가 기능이 아니라 핵심 메커니즘
   - 사용자 모델은 틀릴 수 있다.
   - 잘못된 모델은 topic 단위로 교정/재구성 가능해야 한다.

5. project와 profile을 입력 단계에서 강하게 분리하지 않는다
   - 하나의 artifact가 project 분석에도, profile evidence 추출에도 쓰일 수 있어야 한다.

6. 최종 목표는 응답 생성보다 일관된 이해
   - 좋은 시스템 기준은 그럴듯한 답변이 아니라,
     - correction 반영
     - 일관된 사용자 해석
     - 새 artifact 기반 update
     - 근거 있는 recall
     이다.

---

## 3. 최근까지 반영된 핵심 기능

### 3-1. DB / 기본 구조
- 운영 DB 기준은 `data/memory.db`
- `memory/db.py`, `project_analysis/stores/db.py` 등 경로 정렬
- 루트 `memory.db`는 혼동 가능성이 있으므로 백업 후 정리 권장

### 3-2. 기본 모델 / UI
- 기본 Ollama 모델 방향: `qwen2.5:3b` 기반이었으나, 실제 테스트에서는 경량 모델도 병행 사용
- UI에서 로컬 Ollama 모델 선택 가능하도록 반영됨
  - `/models` API
  - `/chat`의 `model` form field
  - `chat.html` 드롭다운
  - `chat.js`의 로드/선택/localStorage 저장

### 3-3. 문서화
- `requirements.txt` 생성
- `README.md` 정리
- Windows PowerShell에서 Ollama 설치 명령도 README에 반영 가능
  - `irm https://ollama.com/install.ps1 | iex`

### 3-4. prompt 외부화
- response / project ask / review / profile extract / project profile evidence 관련 프롬프트 외부화 방향 유지

### 3-5. recall 원문 확장 1차
- `raw_message_store.py`
  - `search_with_context`
  - `find_context_by_anchor_text`
- `recall_retriever.py`
  - `raw_expansions`
  - `fallback_raw_expansions`

### 3-6. profile evidence -> confirmed profile 승격 1차
- project evidence 경로에 대해 보수적 promotion 로직 존재
- 이후 공용 sync 서비스로 일부 분리됨

---

## 4. 최근 가장 큰 구조 변경

### 텍스트 첨부 프로필 요청을 preview가 아니라 update-first로 변경

이전:
- 텍스트 첨부 + 프로필성 요청
- `ProfileExtractService.extract_from_uploaded_text(...)`
- preview 해석 응답만 생성
- 저장 / sync 없음

현재:
- 텍스트 첨부 + 프로필성 요청
- `ProfileAttachmentIngestService` 경로로 처리
- 흐름:
  1. source 저장
  2. relevant passage 선별
  3. evidence 추출
  4. evidence 저장
  5. memory sync / promotion
  6. 자연어 답변 생성

즉, 이제 txt 블로그/회고/자기서술 문서는 **실제 profile update source**로 취급된다.

---

## 5. 최근 추가/수정된 주요 파일

### 새로 추가된 계열
- `profile_analysis/services/profile_attachment_ingest_service.py`
- `profile_analysis/services/profile_memory_sync_service.py`
- `profile_analysis/stores/uploaded_profile_source_store.py`
- `profile_analysis/stores/uploaded_profile_evidence_store.py`
- `prompts/profile_attachment_answer_system_prompt.txt`

### 수정된 주요 파일
- `app/api.py`
- `tools/ollama_client.py`
- `project_analysis/stores/db.py`
- `project_analysis/services/project_profile_evidence_service.py`
- `project_analysis/services/project_ask_service.py`
- `prompts/system_prompt.txt`
- `prompts/profile_extract_system_prompt.txt`
- `prompts/project_profile_evidence_extract_system_prompt.txt`
- `prompts/project_profile_evidence_answer_system_prompt.txt`
- `prompts/response_builder.py`
- `README.md`
- `requirements.txt`

---

## 6. 프롬프트 정리 방향

### 현재 원칙
- **system prompt는 운영 원칙만** 담는다.
- **사용자 개인 특성은 memory / correction / evidence**가 담당한다.
- profile 관련 프롬프트는 내부 구조화는 하되, 사용자에게는 **자연어 해석문**만 보여준다.

### 이미 반영된 방향
- `system_prompt.txt`
  - 사용자 하드코딩 최소화
  - 정직성 / 검증 / correction 반영 / 근거 기반 업데이트 등 운영 원칙 중심
  - 인칭 기준 규칙 추가

- `profile_extract_system_prompt.txt`
  - 번호형 분류표 출력 제거
  - 사용자에게는 자연어 해석문만 출력
  - 학자/이론/학파 이름 끌어오기 금지

- `project_profile_evidence_extract_system_prompt.txt`
  - evidence-only 추출 강화
  - 과장 억제 / confidence 보수화

- `project_profile_evidence_answer_system_prompt.txt`
  - 자연스러운 대화형 설명 방향으로 조정됨

- `profile_attachment_answer_system_prompt.txt`
  - 텍스트 첨부 후 profile update 답변 전용
  - 질문 복사 금지, 존댓말 유지, 인칭 기준 유지, 템플릿 반복 억제 방향으로 조정 중

---

## 7. 중요한 버그 / 이슈와 현재 상태

### 7-1. 답변이 중간에서 잘리던 문제
- 원인:
  - Ollama `done_reason == length`를 제대로 처리하지 않음
- 조치:
  - `tools/ollama_client.py`에 length 감지 추가
  - 일반 응답은 경고 문구 부착
  - JSON 추출 계열은 `require_complete=True`

### 7-2. memory contamination 문제
- 확인 결과:
  - 과거 system prompt 덩어리가 `profiles`, `corrections`, `states`에 저장돼 있었음
- 영향:
  - 인칭 혼동
  - 현재 정정보다 오염 기억 우선
  - `불편함을 원한다` 같은 잘못된 재진술 발생
- 조치:
  - `response_builder.py`에 오염 텍스트 필터 추가
  - `system_prompt.txt`에 인칭 기준 / 현재 턴 정정 우선 규칙 추가
- 추가 권장:
  - DB 직접 정리

### 7-3. SQLite 정리 권장 SQL
아직 사용자가 직접 실행해야 할 수 있음.

```sql
DELETE FROM states WHERE key = 'current_mood';
DELETE FROM corrections WHERE topic = 'response_style';
DELETE FROM profiles WHERE topic = 'response_style';
```

### 7-4. 텍스트 첨부 답변이 템플릿처럼 보이던 문제
- 초기 원인:
  - 최종 답변이 코드 템플릿 `_build_user_reply()`로 생성됨
- 조치:
  - 현재는 전용 answer prompt + 모델 응답으로 변경됨
- 그러나 아직도 약간의 템플릿감 / 문체 혼용이 남아 있어 추가 조정 중

### 7-5. 나/너/당신 인칭 혼동 문제
- 원인:
  - memory contamination
  - 작은 모델의 취약점
  - 첨부 텍스트 answer 경로에서 질문 원문을 너무 직접 넣던 구조
- 조치:
  - 질문 원문 -> 질문 요지로 축약
  - 전용 answer prompt에 인칭 기준 추가
  - system prompt에도 인칭 기준 규칙 추가
- 상태:
  - 이전보다는 개선됐지만 완전히 해결되진 않았음

### 7-6. 존댓말/반말 혼용 문제
- 원인:
  - 전용 answer prompt가 문체를 충분히 고정하지 못함
- 조치:
  - 존댓말만 사용하도록 prompt 보강
- 상태:
  - 개선 중이나 아직 템플릿감이 남음

---

## 8. 모델 관련 현재 판단

### 실제 테스트에서 나온 판단
- `qwen2.5:3b`
  - CPU 환경에서 timeout 위험이 큼
- `qwen2.5:1.5b`
  - 현실적인 1차 후보
- `gemma3:1b`
  - 상당히 가볍고, 현재 첨부 텍스트 경로 테스트에 자주 사용됨
- `qwen2.5:0.5b`
  - 극단적 경량 fallback

### 현재 인식
- 병목은 단순 버그보다 **로컬 CPU 추론 속도 + 프롬프트 길이 + 응답 길이**에 가까움
- 더 큰 모델로 가는 것보다,
  - 경량 모델 선택
  - 프롬프트 단순화
  - 응답 길이 조정
  이 우선이다.

---

## 9. 지금 시점에서 가장 중요한 남은 과제

### 1순위
1. 텍스트 첨부 profile update 답변의 말투/자연스러움 추가 개선
   - 템플릿감 완화
   - 존댓말 일관성 강화
   - 일반 대화 경로와 톤 간극 줄이기

2. memory contamination 실제 DB 정리
   - `response_style`, `current_mood` 오염 레코드 삭제 여부 확인

3. 작은 모델에서의 인칭 기준 안정화
   - 특히 `나/너/당신` 기준을 더 확실히 유지시키기

### 2순위
4. profile evidence가 너무 쉽게 `candidate_count=0`으로 끝나는지 점검
5. `trusted_search` 실제 구현
6. topic 분류 고도화
7. correction policy 2차

---

## 10. 다음 채팅에서 바로 이어갈 때 추천 프롬프트

아래 문장을 다음 채팅에 붙여 넣으면 이어가기 좋다.

```text
아래는 MK4 현재 상태 요약이다. 이 상태를 기준으로, assistant 작업 폴더(/mnt/data/mk4_work/MK4)를 기준 작업본으로 보고 이어가자. 내가 중간중간 새 MK4.zip을 줄 테니, 그때는 내 로컬본과 assistant 작업본의 차이만 동기화해 줘. 답변은 파일 단위로 주고, 긴 파일은 경로+다운로드 링크 형식도 괜찮다.

현재 상태 핵심:
- 텍스트 첨부 + 프로필성 요청은 preview가 아니라 update-first로 처리된다.
- `ProfileAttachmentIngestService`가 source 저장 -> evidence 추출 -> memory sync -> 자연어 응답을 담당한다.
- UI에서 모델 선택 가능하다.
- memory contamination 문제가 있었고, `response_builder.py`와 `system_prompt.txt`에 방어를 넣었다.
- 다만 아직 텍스트 첨부 answer 경로의 말투가 약간 템플릿처럼 보이고, 존댓말/자연스러움/인칭 기준을 더 다듬을 필요가 있다.
- 오염된 DB 레코드(`states.current_mood`, `profiles.response_style`, `corrections.response_style`)는 실제 삭제 여부를 점검해야 한다.

우선순위:
1) 첨부 텍스트 답변 말투/자연스러움/인칭 기준 추가 개선
2) memory DB 오염 레코드 정리 확인
3) profile evidence 추출/승격 품질 점검
```

---

## 11. 참고

추가 상세 이슈와 해결 기록은 별도 문서에 정리되어 있다.
- `troubleshooting.md`

