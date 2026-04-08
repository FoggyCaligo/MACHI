# MK4 Troubleshooting Log

이 문서는 2026-04-08 기준, MK4 작업 중 실제로 발생했던 문제와 해결 과정을 정리한 기록이다.
목적은 다음과 같다.

- 같은 문제가 다시 생겼을 때 빠르게 원인을 찾기
- 새 채팅으로 넘어가더라도 맥락을 잃지 않기
- 어떤 수정이 설계적 수정이었고, 어떤 수정이 임시 보정이었는지 구분하기

---

## 1. 작업 기준이 ZIP 스냅샷 단위로 끊겨 버리는 문제

### 증상
- 사용자가 `MK4.zip`을 여러 번 업로드할 때마다, 각 수정이 모두 "업로드된 ZIP" 기준으로 따로 작업됨
- 그 결과 1차, 2차, 3차 수정이 누적되지 않고, 모두 초기 ZIP에서 각각 따로 파생되는 형태가 되어 버림

### 원인
- 작업 기준본을 로컬 작업 폴더가 아니라, 매번 새로 업로드된 ZIP으로 잡았기 때문

### 해결
- 기준 작업본을 assistant 로컬 폴더로 고정
- 이후 ZIP은 "기준 교체"가 아니라 "차이 동기화" 용도로만 사용

### 현재 원칙
- 기준 작업 폴더: `/mnt/data/mk4_work/MK4`
- 이후 사용자가 새 ZIP을 주면, 그 ZIP과 현재 작업본의 차이만 반영

---

## 2. UI에서 Ollama 모델 선택이 안 되던 문제

### 증상
- 내부적으로는 `model=None` 전달 경로가 일부 준비되어 있었지만, 실제 UI에서는 모델을 선택할 수 없었음

### 원인
- 다음 연결이 빠져 있었음
  - `/models` API
  - `/chat`의 `model` form field 수신
  - `chat.html`의 모델 드롭다운
  - `chat.js`의 모델 목록 로드 / 선택 / localStorage 저장

### 해결
- `GET /models` 추가
- `POST /chat`에서 `model` 수신
- UI 드롭다운, 새로고침, 기본모델 복귀 버튼 추가
- model 선택값을 localStorage에 저장

### 관련 파일
- `app/api.py`
- `app/static/chat.html`
- `app/static/chat.js`
- `app/static/chat.css`

---

## 3. `requirements.txt`가 없어 README와 실행 절차가 어긋나던 문제

### 증상
- README는 `pip install -r requirements.txt`를 전제로 쓰여 있었는데 실제 파일이 없었음

### 해결
- `requirements.txt` 생성
- README를 현재 구조 기준으로 정리
- Ollama 설치, 모델 pull, UI 진입, `/models` 설명 추가

### 추가 반영
- Windows PowerShell에서 Ollama 설치 명령 추가
  - `irm https://ollama.com/install.ps1 | iex`

---

## 4. 첨부 텍스트 기반 프로필 요청이 "preview"로만 처리되던 문제

### 증상
- 사용자가 블로그 글 txt를 첨부하며 프로필 형성/업데이트 의도로 질문해도,
  실제로는 DB 저장/증거 축적 없이 preview 해석 응답만 반환됨

### 원인
- `app/api.py`에서 `_looks_like_profile_request(...) == True`일 때,
  `ProfileExtractService.extract_from_uploaded_text(...)`로 보내는 구조였음
- 이 서비스는 해석문만 반환하고 저장/동기화는 하지 않음

### 해결 방향
- preview-first를 버리고 update-first로 전환
- 텍스트 첨부 전용 `ProfileAttachmentIngestService` 추가

### 변경 후 흐름
1. 업로드 텍스트 source 저장
2. 관련 passage 선별
3. profile evidence 추출
4. evidence 저장
5. memory sync / promotion
6. 자연어 답변 생성

### 관련 파일
- `profile_analysis/services/profile_attachment_ingest_service.py`
- `profile_analysis/stores/uploaded_profile_source_store.py`
- `profile_analysis/stores/uploaded_profile_evidence_store.py`
- `profile_analysis/services/profile_memory_sync_service.py`
- `app/api.py`

---

## 5. `extract_from_uploaded_text(..., model=...)` 인자 불일치 문제

### 증상
- 에러:
  - `ProfileExtractService.extract_from_uploaded_text() got an unexpected keyword argument 'model'`

### 원인
- `app/api.py`는 `model=`을 넘기도록 바뀌었는데,
  실제 로컬의 `profile_extract_service.py`는 이전 시그니처인 상태였음

### 해결
- `extract_from_uploaded_text(..., model: str | None = None)`로 수정
- 동일하게 내부 `_extract_from_documents(..., model=...)` 경로까지 연결

### 교훈
- API 입구와 서비스 시그니처를 함께 맞춰야 함
- 파일 일부만 교체하면 이런 mismatch가 쉽게 생김

---

## 6. Ollama read timeout 문제

### 증상
- `HTTPConnectionPool(host='localhost', port=11434): Read timed out. (read timeout=150)`

### 원인
- 로컬 CPU 추론 속도가 느림
- 긴 텍스트 + 무거운 모델 + 긴 프롬프트가 겹치면 150초 timeout에 쉽게 걸림

### 대응
- 기본 모델 후보를 경량화해서 테스트
  - `qwen2.5:1.5b`
  - `gemma3:1b`
  - 필요시 `qwen2.5:0.5b`
- 경로별 `num_predict`와 timeout 재조정
- 출력 프롬프트를 줄여 한 번에 생성해야 할 응답량을 감소

### 판단
- 이 문제는 버그라기보다 하드웨어/모델 크기/프롬프트 길이의 합성 병목에 가깝다

---

## 7. 답변이 문장 중간에서 잘리는 문제

### 증상
- 에러는 없는데 답변이 마지막 문장 중간에서 끊김
- 사용자 입장에서는 정상 응답처럼 보이지만 실제로는 불완전함

### 원인
- `tools/ollama_client.py`가 `done_reason == "length"`를 확인하지 않고,
  `content`만 있으면 그대로 정상 응답처럼 반환했음

### 해결
- `done_reason == "length"` 감지 추가
- 일반 응답은 경고 문구 부착
- JSON처럼 완전성이 필요한 호출은 `require_complete=True`로 강제

### 관련 파일
- `tools/ollama_client.py`

---

## 8. 텍스트 첨부 프로필 답변이 템플릿처럼 반복되던 문제

### 증상
- 첨부 텍스트 후 프로필 업데이트 답변이 매번 거의 비슷하게 나옴
- 일반 대화와 말투가 크게 다르고, 즉석 생성 같지 않음

### 원인
- `profile_attachment_ingest_service.py`에서 최종 답변을 모델이 아니라 코드 템플릿 `_build_user_reply()`가 만들고 있었음

### 해결
- `_build_user_reply()` 제거
- `prompts/profile_attachment_answer_system_prompt.txt` 추가
- 최종 답변도 모델이 하도록 변경

### 관련 파일
- `profile_analysis/services/profile_attachment_ingest_service.py`
- `prompts/profile_attachment_answer_system_prompt.txt`
- `config.py`

---

## 9. 사용자 질문 문장을 그대로 답변에 복사하던 문제

### 증상
- 사용자가 한 질문 문장을 모델이 거의 그대로 다시 말함
- 특히 `너가 나라는 사람에 대해...` 같은 문장이 답변에 그대로 섞임

### 원인
- 첨부 텍스트 답변 경로에서 `[사용자의 현재 질문]`에 원문 전체를 그대로 넣고 있었음
- 전용 answer prompt도 "현재 말투를 따라가라"에 가깝게 작동하면서 echo가 발생

### 해결
- `_summarize_user_request()` 추가
- 질문 원문 대신 "질문의 요지"만 answer prompt에 넣도록 변경
- 전용 answer prompt에 질문 복사 금지 규칙 추가

### 관련 파일
- `profile_analysis/services/profile_attachment_ingest_service.py`
- `prompts/profile_attachment_answer_system_prompt.txt`

---

## 10. 첨부 텍스트 답변에서 나/너 기준이 흔들리던 문제

### 증상
- 모델이 사용자의 `나/내/...`를 자기 자신 관점처럼 따라 쓰거나,
  사용자의 `너/네/...`를 현재 화자의 인칭으로 기계적으로 복사함

### 원인
- 첨부 텍스트 답변 경로는 일반 대화용 `system_prompt.txt`를 사용하지 않고,
  별도 `profile_attachment_answer_system_prompt.txt`만 사용함
- 그래서 `system_prompt.txt`에 넣어둔 인칭 기준 규칙이 이 경로에 적용되지 않았음

### 해결
- `profile_attachment_answer_system_prompt.txt`에도 인칭 기준 규칙 추가
  - `나/내/...` = 사용자
  - `너/네/...` = AI
- 사용자 질문 문장 복사 금지
- 사용자의 인칭 표현을 답변 화자의 인칭으로 기계적으로 따라 쓰지 말 것 명시

---

## 11. 존댓말/반말이 섞이던 문제

### 증상
- 한 답변 안에서 존댓말과 반말이 섞임

### 원인
- 전용 answer prompt가 말투를 충분히 고정하지 못했고,
  작은 모델이 문체를 일정하게 유지하지 못함

### 해결
- `profile_attachment_answer_system_prompt.txt`에
  - 항상 존댓말만 사용
  - 반말 금지
  를 강하게 명시
- 입력 메타정보를 줄여 "보고서 톤"을 약화

---

## 12. 말투가 갑자기 바뀌는 문제

### 증상
- 일반 대화와 첨부 텍스트 후 답변의 분위기가 크게 다름

### 원인
- 실제로 응답 경로가 달랐음
  - 일반 대화: system prompt + memory + 모델 즉석 생성
  - 첨부 텍스트: extract는 모델, final answer는 처음엔 코드 템플릿, 이후엔 별도 answer prompt 모델

### 해결
- 첨부 경로도 최종 답변을 모델이 하도록 통일
- 그러나 여전히 system prompt와 다른 전용 prompt를 사용하기 때문에, 톤 차이가 약간 남을 수 있음

### 후속 과제
- 프롬프트 간 스타일 간극을 더 줄이기
- 필요하면 공통 스타일 레이어를 둘 것

---

## 13. 메모리 오염(memory contamination) 문제

### 증상
- 모델이 `당신의 불편함을...`, `불편함을 원한다는 것을 이해하고...` 같은 이상한 응답을 반복
- 현재 정정보다 과거 잘못된 기억을 더 세게 따름

### 확인 결과
- `memory.db` 안의 `profiles`, `corrections`, `states`에 예전 system prompt 덩어리가 저장돼 있었음
- 예:
  - `profiles.topic = response_style`
  - `corrections.topic = response_style`
  - `states.key = current_mood`
  에 system prompt 텍스트가 들어가 있었음

### 해결
- 오염 레코드 삭제 권장

```sql
DELETE FROM states WHERE key = 'current_mood';
DELETE FROM corrections WHERE topic = 'response_style';
DELETE FROM profiles WHERE topic = 'response_style';
```

### 추가 대응
- `response_builder.py`에 오염 텍스트 필터 추가
- system prompt에 현재 턴 정정 우선, 인칭 기준 유지 규칙 추가

---

## 14. `response_builder.py`가 오염된 기억을 그대로 주입하던 문제

### 증상
- memory DB에 잘못 저장된 긴 system-like 문장이 그대로 모델에게 주입됨
- 그 결과 현재 대화 인칭 기준과 메모리의 2인칭 표현이 섞임

### 해결
- `response_builder.py`에 필터 추가
  - system prompt 냄새가 나는 메모리 문장은 제외
  - 너무 긴 오염 문장 제외
  - `response_style`, `current_mood` 등 오염 가능성이 큰 항목은 더 엄격하게 필터링

### 목적
- 저장 메모를 무조건 진실로 쓰지 않고, 최소한의 위생 처리 후 주입

---

## 15. `system_prompt.txt`에 사용자 개인 특성이 과하게 하드코딩되어 있던 문제

### 증상
- 시스템 프롬프트에 사용자의 사고방식, 감정 구조, 선호 설명 방식 등이 강하게 박혀 있었음
- memory/correction이 바뀌어도 system prompt가 계속 같은 사용자상을 강제할 수 있는 구조였음

### 해결 방향
- `system_prompt.txt`를 얇게 만듦
- 사용자 개인 특성은 최대한 제거
- 운영 원칙만 남김

### 남긴 것
- 정직성
- 검증 우선
- correction 반영
- 저장된 프로필도 검증 대상
- 과장 금지
- 근거 기반 업데이트

### 추가 반영
- 현재 대화의 인칭 기준 명시
- 저장 메모의 `당신`, `이 사용자`, `사용자는` 같은 표현을 현재 화자의 인칭으로 기계적으로 복사하지 말 것 명시

---

## 16. 프로필 추출 프롬프트가 번호형 분류표를 강제하던 문제

### 증상
- `1) 반복되는 사고 방식`, `2) 선호`, `3) NEED` 식의 기계적 출력
- 학자/이론 이름을 원문 밖에서 끌어오는 문제

### 해결
- `profile_extract_system_prompt.txt`를 자연어 해석 중심으로 재작성
- 내부 분류는 해도, 사용자에게는 분류표를 노출하지 않도록 변경
- 학자/이론/학파 이름 끌어오기 금지

---

## 17. project profile evidence 추출 프롬프트가 과장된 후보를 뽑을 수 있던 문제

### 해결
- `project_profile_evidence_extract_system_prompt.txt`를 evidence-only 추출 성격으로 정리
- 애매하면 넣지 말고, 많이 뽑는 것보다 적고 정확하게 뽑도록 유도
- confidence를 더 보수적으로 사용

---

## 18. 새 store 파일이 잘못된 폴더에 들어가 import 에러가 난 문제

### 증상
- 에러:
  - `ModuleNotFoundError: No module named 'profile_analysis.stores.uploaded_profile_evidence_store'`

### 원인
- 새로 만든 store 파일이 `profile_analysis/stores/`가 아니라 다른 위치에 들어가 있었음

### 해결
- 아래 위치로 정확히 이동/생성
  - `profile_analysis/stores/uploaded_profile_source_store.py`
  - `profile_analysis/stores/uploaded_profile_evidence_store.py`
  - `profile_analysis/stores/__init__.py`

---

## 19. 텍스트 첨부 답변이 너무 짧고 자주 잘리던 문제

### 원인
- `profile_attachment_ingest_service.py`에서 answer client가 `num_predict=320`으로 너무 짧게 잡혀 있었음

### 해결
- answer client의 `num_predict`를 상향
- 질문 복사 억제와 함께 응답 길이를 조금 늘릴 수 있게 조정

### 주의
- 너무 높이면 다시 timeout 위험이 증가하므로, 모델과 하드웨어에 맞게 미세조정 필요

---

## 20. 현재 남아 있는 과제

### 우선순위 높음
1. memory DB의 오염 레코드 실제 삭제 여부 확인
2. 일반 대화와 첨부 업데이트 답변 톤의 간극 추가 축소
3. 작은 모델에서의 인칭/정정 우선순위 안정화
4. profile evidence가 너무 쉽게 `candidate_count=0`이 되는지 점검

### 우선순위 중간
5. `trusted_search` 실제 구현
6. topic 분류 고도화
7. correction policy 2차
8. README와 실제 동작의 최종 일치 점검

---

## 21. 재발 방지 원칙

- ZIP은 기준본이 아니라 동기화 재료로만 사용한다.
- 사용자 개인 특성은 되도록 system prompt가 아니라 memory/correction이 담당한다.
- 저장된 memory는 무조건 신뢰하지 말고, 주입 전에 필터링한다.
- 첨부 텍스트 경로와 일반 대화 경로가 서로 다른 화자처럼 보이지 않게 한다.
- 작은 모델일수록 질문 원문 복사, 인칭 혼동, 과거 메모 오염에 취약하므로 입력 포맷을 더 보수적으로 설계한다.
