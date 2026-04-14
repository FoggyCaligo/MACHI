# MK4

MK4는 "답변을 잘하는 챗봇"보다, 시간이 지날수록 더 일관되게 사용자를 이해하는 **로컬 개인화 인지 시스템**을 목표로 하는 프로젝트입니다.

핵심은 단순한 대화 로그 누적이 아닙니다. 일반 채팅, 첨부 텍스트, ZIP artifact, correction을 바탕으로 **사용자 모델을 형성하고**, 틀리면 **다시 깨고 재구성할 수 있는 memory 구조**를 만드는 것이 목표입니다.

상위 프로젝트인 `MACHI` 전체 관점에서 보면, MK4는 그 장기 목표 중 특히 **"기억(memory) 계층"** 을 실제 구조와 코드로 구현하는 현재 작업 축입니다.  
즉, MACHI가 장기적으로 개인 전용 인지 시스템 전체를 지향한다면, MK4는 그중 **evidence-first memory / correction / topic / promotion / reuse** 를 담당하는 실험이자 구현 단계라고 볼 수 있습니다.

## 1. 이 프로젝트가 지향하는 것

MK4는 다음을 우선합니다.

- fact 몇 개를 저장하는 것보다 **user model**을 더 잘 형성하기
- 지금 한 번 그럴듯하게 답하는 것보다 **시간이 지날수록 더 일관되게 이해하기**
- append-only 로그보다 **update / correction / rebuild 가능한 memory**
- prompt에 사용자를 박아 넣는 것보다 **memory-driven personalization**
- 첨부 텍스트, ZIP, project artifact도 모두 **evidence-first**로 처리하기

한 줄로 요약하면:

> MK4는 "정답을 빨리 말하는 모델"보다, "나를 더 일관되게 이해하고 틀리면 다시 고칠 수 있는 로컬 시스템"을 만들려는 프로젝트입니다.

---

## 2. 핵심 철학

### 2-1. Memory is not append-only

MK4에서 기억은 단순 누적 로그가 아닙니다.

- 새 evidence로 업데이트될 수 있음
- correction으로 재구성될 수 있음
- 오래되거나 신뢰도가 낮은 내용은 정리될 수 있음

즉, 저장된 memory도 절대 진실이 아니라 **재검증 대상**입니다.

### 2-2. Fact보다 user model이 우선

MK4는 "사용자가 무슨 말을 했는가" 자체보다 아래를 더 중요하게 봅니다.

- 어떤 설명 방식을 선호하는지
- 어떤 사고 패턴을 보이는지
- 어디에서 correction이 반복되는지
- 무엇을 중요하게 여기는지

### 2-3. Evidence-first

원문이나 artifact를 곧바로 profile로 확정하지 않습니다.

기본 흐름은 다음과 같습니다.

```text
conversation / attachment / project artifact
-> evidence
-> general / candidate / confirmed
-> sync / promotion / rebuild
-> next-turn reuse
```

### 2-4. Correction is core

MK4에서 correction은 부가기능이 아닙니다.

- 잘못 형성된 profile을 깨고
- 현재 사용자상을 다시 구성하고
- memory 오염을 나중에라도 되돌릴 수 있게 만드는

핵심 메커니즘입니다.

### 2-5. Prompt-driven persona보다 memory-driven personalization

system prompt는 운영 원칙만 얇게 유지하고, 실제 개인화는 아래가 담당합니다.

- memory
- evidence
- correction
- topic

### 2-6. 외부 라이브러리 최소화

MK4는 기능을 빨리 붙이기 위해 외부 라이브러리를 계속 늘리는 방향을 지향하지 않습니다.

- 장기 유지보수와 Python 버전 호환성을 더 우선합니다.
- 특정 버전 상한에 프로젝트 전체가 묶이는 의존성은 가능한 한 줄입니다.
- 구조적으로 단순한 기능은 자체 구현으로 대체하는 편을 선호합니다.
- 외부 라이브러리는 "편해서"가 아니라, 장기적으로도 유지 가치가 분명할 때만 남깁니다.

즉, MK4는 기능 확장보다도 `오래 살아남는 로컬 시스템`이라는 기준으로 기술 선택을 합니다.

---

## 3. 현재 구조의 큰 그림

MK4는 크게 세 계층으로 볼 수 있습니다.

### 3-1. 입력 채널

- 일반 채팅
- 첨부 텍스트
- ZIP artifact
- project 질문
- correction 입력

이 채널들은 서로 다르지만, 장기적으로는 같은 memory 의미론으로 수렴해야 합니다.

### 3-2. 공통 memory 의미론

- `general`: 저장 가치는 있지만 기본 응답에는 주입하지 않는 정보
- `candidate`: 승격 후보
- `confirmed`: 현재 모델이 보고 있는 사용자상

### 3-3. Correction 분류 체계 (2026-04-13 강화)

**Correction은 대상에 따라 3가지로 분류**:

```
profile: 사용자 모델 자체 재정정
  예) "내가 말한 취향이 틀렸다", "나는 그런 사람이 아니다"
  영향: profile rebuild에 반영, profile 정정으로 이전 정보 무효화

topic_fact: 설명/정보 정정
  예) "그건 틀렸어", "그건 이렇게 작동해", "이건 다르다"
  영향: correction store에 보관되지만 profile rebuild에는 미포함
         다음 회상 시 conflict 판단에 사용

response_behavior: 답변 방식/태도 정정
  예) "이렇게 답하지 말아줄래?", "더 짧게 답해줄 수 있어?", "이 방식은 싫어"
  영향: memory에만 보관, response_behavior 후보로 저장되지 않음
        향후 응답 스타일 추출용 자료로만 유지
```

각 correction은 reason 필드에 `"target_kind:reason_text"` 형식으로 저장되어,
나중에 policy를 적용할 때 구분됨.

### 3-4. Evidence 흐름

```
입력 (채팅 / 첨부 / artifact / 정정)
  ↓
Evidence 추출 (model 기반, 규칙 제외)
  ↓
Tier 배정 (general / candidate / confirmed)
  ↓
Store 저장 (profile / correction / episode / state)
  ↓
Conflict 판단 (기존 correction 확인)
  ↓
다음 턴 반영 (retrieval / response building / profile reconstruction)
```

`confirmed`도 절대 진실이 아니라, **현재 시점의 가설적 사용자상**입니다.

### 3-3. 두 개의 축

- `topic`: 의미 축
- `project_id`: 출처 축

둘은 대체 관계가 아닙니다.

- `topic`은 어떤 의미 맥락에 속하는지
- `project_id`는 어떤 artifact / file 묶음에서 왔는지

를 나타냅니다.

다만 사용자 UI에서는 raw `project_id`를 직접 기억하게 두지 않고,
프로젝트를 **이름(project name)으로 선택**하고 내부적으로만 `project_id`를 유지하는 방향으로 정리하고 있습니다.

---

## 4. 주요 동작 방식

### 4-1. Topic routing

현재 대화나 evidence는 `TopicRouter`를 통해 다음 중 하나를 탑니다.

1. 현재 active topic 유지
2. 기존 topic에 attach
3. 새 topic 생성

이 판단은 문자열 일치보다 **임베딩 기반 의미 유사도**를 우선합니다.

### 4-2. Chat memory update

일반 채팅은 다음 흐름으로 처리됩니다.

1. user message 저장
2. response retrieval
3. agent 응답 생성
4. chat evidence 추출
5. evidence normalization
6. topic resolution
7. memory apply / promotion / rebuild

### 4-3. Attachment update-first

첨부 텍스트는 preview-only가 아니라 **update-first** 방향입니다.

1. source 저장
2. passage selection
3. evidence extract
4. evidence store
5. memory sync
6. 그 결과를 바탕으로 자연어 답변 생성

### 4-4. Project artifact flow

ZIP 업로드 시:

1. project 생성
2. 파일 추출
3. file / chunk 저장
4. project evidence 추출
5. profile evidence sync
6. 이후 project 기반 질문 응답 가능

즉, project는 단순 검색 자료가 아니라 **장기 evidence source**이기도 합니다.

---

## 5. 현재 코드 구조

### `app/`

- `app/api.py`: FastAPI 엔트리포인트
- `app/request_orchestrator.py`: 요청 타입 분기
- `app/orchestrator.py`: 일반 채팅 orchestration
- `app/agent.py`: 모델 응답 호출

### `memory/`

- `services/topic_router.py`: active topic 유지 / attach / create
- `services/memory_ingress_service.py`: 공통 ingress
- `services/memory_apply_service.py`: 공통 apply / promotion / rebuild
- `services/chat_evidence_service.py`: chat evidence 추출
- `services/evidence_normalization_service.py`: evidence 정규화
- `retrieval/response_retriever.py`: 응답용 memory retrieval
- `stores/`: topics, profiles, corrections, states, evidences 등 저장소

### `profile_analysis/`

- 첨부 텍스트 source 저장
- profile evidence 추출
- uploaded evidence 저장
- memory sync

### `project_analysis/`

- ZIP ingest
- project file / chunk 저장
- project retrieval
- project artifact에서 profile evidence 추출

### `prompts/`

- 운영 원칙 중심 system prompt
- chat update extract prompt
- profile attachment answer prompt
- project / review / evidence extract prompt

### `tools/`

- Ollama 호출
- embedding 생성
- response continuation 처리
- reply guard

---

## 6. 현재 기술 스택

- Python
- FastAPI
- Uvicorn
- SQLite
- Ollama
- `sentence-transformers`
- NumPy

기본 패키지는 `requirements.txt`에 정리되어 있습니다.

의존성 원칙:
최근에도 chunking 라이브러리와 `sqlite-vec`을 제거하고, 가능한 부분은 자체 구현과 표준 라이브러리 중심으로 정리했습니다. MK4는 기능 추가보다도 장기 유지보수성과 버전 독립성을 더 중요하게 봅니다.

---

## 7. 실행 방법

### 7-1. 가상환경

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Git Bash:

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

### 7-2. Ollama 준비

Ollama가 먼저 설치되어 있어야 합니다.

예:

```powershell
irm https://ollama.com/install.ps1 | iex
ollama --version
```

예시 모델:

```bash
ollama pull qwen2.5:3b
ollama pull gemma3:1b
ollama pull llama3.2:3b
ollama pull gemma3:4b
```

### 7-3. 서버 실행

```bash
python -m uvicorn app.api:app --reload --host 127.0.0.1 --port 8000
```

브라우저:

```text
http://127.0.0.1:8001/ui
```

---

## 8. 현재 기본 설정

현재 코드 기준 주요 기본값:

- 기본 LLM: `qwen2.5:3b`
- 기본 embedding: `intfloat/multilingual-e5-small`
- active topic 유지 threshold: `0.73`
- existing topic attach threshold: `0.78`
- 운영 DB 경로: `data/memory.db`

이 값들은 절대 규칙이 아니라, 로컬 환경과 실제 사용 경험에 따라 조정 가능한 운영값입니다.

운영 timeout도 `config.py`에 모아 관리합니다.

- 일반 응답 / 첨부 응답 / project 응답 timeout
- chat extract / attachment extract / route classify timeout
- Ollama 기본 요청 timeout / 모델 목록 timeout
- UI 요청 timeout (`/ui-config`를 통해 프론트에 전달)

---

## 9. API / 사용 흐름

### 기본 엔드포인트

- `GET /`: 서버 상태 확인
- `GET /ui`: 간단한 채팅 UI
- `GET /ui-config`: 프론트 요청 timeout 등 UI 설정
- `GET /models`: 로컬 Ollama 모델 목록
- `GET /projects`: 최근 프로젝트 목록
- `POST /chat`: 일반 채팅 / 첨부 텍스트 / ZIP artifact 처리
- `GET /recall?query=...`: memory recall 조회

### `/chat`의 대표 흐름

- `message`만 있으면 일반 채팅
- `message + text file`이면 일반 채팅 또는 profile update 경로
- `zip file`이면 project artifact ingest
- `zip file + project_name`이면 사용자 지정 이름으로 project 생성
- `project_id + message`이면 project 기반 질문

UI에서는 ZIP 업로드 후 프로젝트가 이름으로 목록에 등록되고, 이후에는 목록에서 선택해서 이어서 질문합니다.

---

## 10. 현재 어디까지 와 있는가

현재 코드에 이미 들어와 있는 핵심 뼈대는 다음과 같습니다.

- topic 객체화
- topic router 기반 active/attach/create
- update-first attachment 처리
- 공통 ingress / apply 구조
- chat / uploaded_text / project_artifact evidence 통합
- general / candidate / confirmed 분기
- evidence pool 기반 promotion
- project artifact -> profile evidence sync
- ResponseRunner 기반 continuation 처리

즉, MK4는 아직 실험 중인 프로젝트이지만, 단순한 아이디어 문서 수준은 아니고 **memory 시스템의 실제 골격이 이미 코드에 들어와 있는 상태**입니다.

---

## 11. 아직 중요한 미완 과제

현재 우선순위가 높은 과제는 대략 다음과 같습니다.

1. 일반 채팅 품질을 첨부 / project 수준의 memory 처리 품질까지 끌어올리기
2. `general / candidate / confirmed` 의미론을 전 채널에서 더 엄밀하게 통일하기
3. source lookup layer 설계 및 도입
4. correction을 topic 수준 rebuild까지 확장하기
5. retrieval 철학과 budget을 더 정교하게 정리하기
6. 실제 속도/품질 측정 루프 만들기
7. 남아 있는 하드코딩 / 레거시 브리지 / 중복 구현 정리
8. 응답 프롬프트를 더 가볍게 다이어트하되, memory 구조 신호는 유지하는 균형점 찾기

---

## 12. 이 프로젝트가 중요하게 보는 원칙

MK4를 수정할 때는 아래 원칙을 강하게 유지합니다.

- assistant 발화는 profile tier 재료로 쓰지 않기
- 문자열 의미 해석 하드코딩 줄이기
- 실패를 fallback으로 감추지 않기
- general은 넓게 저장하되 기본 주입하지 않기
- correction이 오면 과거 profile도 다시 깨질 수 있어야 하기
- prompt 하드코딩보다 memory 구조를 우선하기
- 최신 로컬 기준본 위에서만 순차적으로 작업하기

---

## 13. 2026-04-13 저녁 개선사항

### 13-1. Correction Target Kind 분류 체계 도입

**문제**: 기존 code에서 correction을 일괄적으로 처리했으나, 정정이 **어떤 대상을 정정하는지** 명확히 구분할 필요가 있었습니다.

**해결책**: Correction을 아래 3가지로 분류

#### 1) `profile` - 사용자 모델 정정
- 사용자가 자신의 특성, 취향, 가치관을 정정하는 경우
- 예: "내가 그렇게 생각하지 않아", "그건 내 성향이 아니야"
- **동작**: Profile rebuild에 **직접 반영**, 기존 profile 무효화
- **코드**: `MemoryApplyService._has_conflicting_active_correction()` 에서 `target_kind == "profile"` 검사

#### 2) `topic_fact` - 설명/정보 정정
- 사용자가 assistant의 설명이나 정보 오류를 지적하는 경우
- 예: "그건 틀렸어", "이건 다르게 작동해", "이건 사실이 아니야"
- **동작**: Correction store에 보관되지만 profile rebuild에는 **미포함**
- **다음 회상 시**: conflict 판단 시 참고, 같은 topic에 다시 profile을 형성하려 할 때 추가 근거로 사용
- **코드**: `ProfileRebuilder.rebuild_topic()` 에서 profile correction만 필터링 사용

#### 3) `response_behavior` - 답변 방식/태도 정정
- 사용자가 답변 스타일이나 대화 태도를 정정하는 경우
- 예: "이렇게 길게 답하지 마", "더 존댓말로 해줄 수 있어?", "이 방식은 싫어"
- **동작**: Memory에만 저장되며, 향후 **응답 스타일** 정책 학습의 근거로만 사용
- **코드**: Correction store에 저장되지만, profile이나 topic rebuild에는 미반영

### 13-2. 구현 상세

#### `EvidenceNormalizationService`
```python
ALLOWED_CORRECTION_TARGET_KINDS = {
    "profile",
    "topic_fact", 
    "response_behavior",
}

def normalize_correction_target_kind(self, value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in self.ALLOWED_CORRECTION_TARGET_KINDS else ""
```
- Extraction prompt에서 받은 `target_kind`를 검증, 허용된 값만 통과

#### `MemoryApplyService`
```python
def _correction_target_kind_from_reason(self, reason: str | None) -> str:
    text = str(reason or "").strip()
    prefix, has_separator, _rest = text.partition(":")
    if has_separator and prefix in {"profile", "topic_fact", "response_behavior"}:
        return prefix
    return "topic_fact"

def _encode_correction_reason(self, *, reason: str | None, target_kind: str | None) -> str:
    # reason을 "target_kind:reason_text" 형식으로 저장
```
- Correction의 reason 필드에 `"target_kind:reason_text"` 형식으로 저장
- 나중에 policy 적용 시 parsing해서 처리

#### `ProfileRebuilder`
```python
latest_profile_correction = next(
    (item for item in corrections if self._correction_target_kind(item.get("reason")) == "profile"),
    None,
)
if latest_profile_correction:
    # profile rebuild에 사용
```
- 모든 correction을 저장하되, **profile 정정만** 실제 rebuild에 사용

### 13-3. Chat Update Extraction Prompt 강화

`chat_update_extract_system_prompt.txt`에 `target_kind` 필드 추가:

```json
{
  "correction_candidate": {
    "content": string,
    "reason": string,
    "target_kind": "profile" | "topic_fact" | "response_behavior" | "",
    "confidence": number
  } | null
}
```

**프롬프트 가이드**:
- "사용자가 assistant의 설명 자체를 정정하면 → `target_kind: "topic_fact"`"
- "사용자가 사용자 모델 자체를 정정하면 → `target_kind: "profile"`"
- "사용자가 답변 방식이나 대화 태도를 바로잡으면 → `target_kind: "response_behavior"`"

### 13-4. 메모리 노이즈 필터 강화

`response_builder.py`에 더 정교한 시스템 프롬프트 및 정책 echo 감지:

```python
MEMORY_NOISE_PATTERNS = (
    "당신은 특정 사용자를 장기적으로 보조하는 개인 ai 어시스턴트다",
    "이 시스템 프롬프트는",
    "최종 운영 지시",
    # ...
)

POLICY_ECHO_PATTERNS = (
    "현재 턴의 명시적 진술",
    "최신 correction",
    "기계적으로 복사하지",
    # ...
)
```

- System prompt 문장이 profile에 들어가는 것을 더 강하게 차단
- Assistant가 자신의 정책을 반복하는 것도 차단

### 13-5. 왜 이 개선이 중요한가

1. **Correction 의도의 명확화**: "틀렸어"라는 정정이 정보 오류인지, 자기 모델 정정인지, 태도 불만인지 명확히 구분

2. **Profile 무결성 강화**: Profile rebuild 시 자신의 취향/특성 정정만 반영, 사실 오류 정정으로 인한 profile 오염 방지

3. **다층적 정정 처리**: 같은 "correction" 타입이지만, 각각 다른 메모리 계층에 영향을 주도록 설계

4. **향후 확장성**: response_behavior 정정을 모아두면, 향후 "사용자의 선호 응답 방식" 학습 가능

### 13-6. 다음 단계

- `general` tier의 promotion 조건에서 `topic_fact` 정정도 참고하기
- Conflict detection 로직을 `topic_fact` 정정까지 확장하기
- Response behavior 정정을 바탕으로 응답 스타일 가이드 자동 생성 고려
- Message/embedding 캐시 및 성능 최적화

---

## 13. 문서 가이드

프로젝트 문서는 다음 성격으로 나뉩니다.

- `docs/프로젝트_요구사항/MK4_프로젝트_핵심원칙.md`
  - 쉽게 바뀌지 않을 철학과 장기 원칙
- `docs/프로젝트_진행상황/진행상황.txt`
  - 현재 코드 기준 완료 / 미완 정리
- `docs/프로젝트_진행상황/troubleshooting_updated_MK4.md`
  - 왜 설계 방향이 바뀌었는지에 대한 구조적 기록

README는 이 셋을 요약한 **프로젝트 입구 문서** 역할을 맡습니다.

---

## 14. 마무리

MK4는 데모형 챗봇 프로젝트가 아니라,

- 시간이 지날수록 더 나를 이해하고
- 틀리면 다시 고칠 수 있고
- 텍스트 / artifact / 대화 전체를 근거로 삼으며
- 로컬 환경에서 실제로 굴러가는

personalization system을 만드는 쪽에 더 가깝습니다.

그래서 이 프로젝트는 단기적으로 답변만 예쁘게 만드는 것보다,
**구조 일관성, 재구성 가능성, evidence 기반 memory, 로컬 실행 가능성**을 더 중요하게 봅니다.
