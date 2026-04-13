# MK4

MK4는 **답변을 잘하는 챗봇**보다, **시간이 지날수록 더 일관되게 사용자를 이해하는 로컬 개인화 인지 시스템**을 목표로 하는 개인 프로젝트입니다.

이 프로젝트의 핵심은 단순한 메모 누적이 아닙니다. MK4는 대화, 첨부 텍스트, ZIP artifact, correction을 바탕으로 **사용자 모델을 형성하고, 틀리면 다시 깨고 재구성할 수 있는 구조**를 지향합니다.

> 이 README는 초기에 업로드된 ZIP 스냅샷이 아니라, **현재 채팅에서 합의·수정된 최신 설계 방향**을 기준으로 작성되었습니다.

---

## 1. 프로젝트 목표

MK4의 목표는 다음과 같습니다.

- 사용자의 말투나 사실 몇 개를 외우는 것이 아니라, **사고 방식·설명 선호·정정 패턴·중요 관심사**를 일관되게 이해하기
- 새 artifact(텍스트, ZIP, 프로젝트 문서)가 들어오면, 이를 단순 참고자료가 아니라 **실제 profile update source**로 활용하기
- 잘못 형성된 이해를 고치기 위해, 기억을 append-only 로그가 아니라 **update / rebuild / discard 가능한 구조**로 다루기
- 답변의 그럴듯함보다, **근거 있는 사용자 이해와 재구성 가능성**을 우선하기

---

## 2. 핵심 철학

### 2-1. Memory is not append-only

MK4에서 기억은 단순 누적 로그가 아닙니다.

기억은:
- 새 evidence로 업데이트될 수 있고
- correction으로 재구성될 수 있고
- 오래되거나 신뢰도 낮은 내용은 버릴 수 있어야 합니다.

즉, 저장된 기억도 절대 진실이 아니라 **재검증 대상**입니다.

### 2-2. Fact 저장보다 user model 형성이 우선

MK4는 “사용자가 무슨 말을 했는가” 자체보다,

- 어떤 설명을 선호하는지
- 어떤 방식으로 사고하는지
- 어디서 correction이 반복되는지
- 무엇을 NEED로 느끼는지

같은 **사용자 모델(user model)**을 더 중요하게 봅니다.

### 2-3. Evidence-first

문서, 블로그 글, ZIP, 프로젝트 artifact는 곧바로 profile로 확정하지 않습니다.

기본 구조는 다음과 같습니다.

**artifact / conversation → evidence → candidate / general / confirmed**

즉 원문을 바로 사실로 박지 않고, **evidence를 거쳐 profile 상태를 조정**합니다.

### 2-4. Correction is core, not optional

MK4에서 correction은 부가 기능이 아닙니다.

- 잘못된 profile을 수정하고
- 기존 이해를 깨고 다시 짜고
- 현재 모델이 보고 있는 사용자를 업데이트하는

핵심 메커니즘입니다.

### 2-5. Prompt-driven persona가 아니라 memory-driven personalization

system prompt에 사용자의 성격을 강하게 하드코딩하지 않습니다.

운영 원칙은 prompt에 두되,
실제 개인화는 **memory / correction / evidence / topic** 구조가 담당합니다.

---

## 3. 현재 설계 구조

### 3-1. 두 축: topic과 project

MK4에는 서로 다른 두 축이 있습니다.

#### topic
- 의미적 대분류 축
- 현재 대화가 어떤 큰 주제 흐름 위에 있는지 관리
- 사용자 모델, 프로필 재구성, topic attach/create 판단에 사용

#### project_id
- artifact / ZIP / file / chunk의 출처 축
- 어떤 파일 묶음에서 나온 evidence인지 추적
- retrieval scope를 제한하고, 서로 다른 프로젝트를 섞지 않게 하는 역할

즉:
- **topic = 의미 축**
- **project_id = 출처 축**

이 둘은 대체 관계가 아닙니다.

### 3-2. Active topic 구조

MK4는 topic을 채팅 1개에 고정하지 않습니다.

매 턴마다:
1. 현재 active topic이 유지되는지 먼저 확인하고
2. 유지되지 않으면 기존 topic 중 붙을 곳이 있는지 보고
3. 없으면 새 topic을 생성합니다.

이때 topic은 텍스트명 일치가 아니라 **임베딩 기반 의미 유사도**로 비교합니다.

### 3-3. Topic은 문자열이 아니라 객체

이제 topic은 단순 문자열 컬럼이 아니라 `topics` 테이블의 독립 객체입니다.

topic은 대략 다음 정보를 가집니다.

- name
- summary
- embedding
- confidence
- usage_count
- created_at / updated_at / last_used_at

현재 topic summary는 **2문장 요약**을 기본 단위로 사용합니다.

### 3-4. General / Candidate / Confirmed

현재 MK4에서 profile 관련 상태는 대략 이렇게 이해하면 됩니다.

#### general
- 기억할 가치는 있지만, 기본 주입할 정도로 강하게 신뢰하진 않는 정보
- DB에는 남기되, 매 턴 기본 context에는 넣지 않음
- 필요할 때만 검색
- 일정 기간(현재 기본 90일) 이후 자동 폐기 가능

#### candidate
- 승격 후보
- 비교적 강한 evidence이지만, 바로 기본 사용자상에 넣기 전의 중간 상태

#### confirmed
- “절대 확정 진실”이 아니라, **현재 모델이 보고 있는 사용자상**
- 기본 응답 생성 시 더 강하게 반영되는 profile
- correction으로 다시 깨지고 재구성될 수 있음

### 3-5. 고기억가치 발화 처리

다음과 같은 신호가 있으면, 단순 general보다 **candidate 또는 confirmed** 쪽으로 더 강하게 다룹니다.

- 자기서술 1인칭 단정문
- 반복적 correction
- 강한 확신 표현
- 구체적 사건 / 배경 설명

즉, topic 분류보다 **기억 가치**가 더 크다고 판단되면 더 높은 계층으로 올릴 수 있습니다.

---

## 4. 현재 주요 컴포넌트

### app/
- `app/api.py` : FastAPI 엔트리포인트
- `app/orchestrator.py` : 일반 대화 처리 오케스트레이션
- `app/agent.py` : 모델 응답 호출

### memory/
- `memory/services/topic_router.py` : active topic 유지 / attach / create 결정
- `memory/stores/topic_store.py` : topic 객체 저장/조회
- `memory/stores/state_store.py` : active topic 등 state 저장
- `memory/policies/extraction_policy.py` : 대화에서 어떤 memory update를 만들지 결정
- `memory/policies/conflict_policy.py` : correction 충돌 반영 및 rebuild
- `memory/summarization/profile_rebuilder.py` : topic/profile 재구성
- `memory/retrieval/response_retriever.py` : 응답용 context retrieval

### profile_analysis/
- 첨부 텍스트에서 evidence 추출
- profile memory sync
- uploaded profile source / evidence 저장

### project_analysis/
- ZIP artifact ingest
- project file / chunk / review 관리
- project 기반 질의응답
- project artifact에서 profile evidence 추출

### prompts/
- `system_prompt.txt` : 운영 원칙 중심 system prompt
- `profile_attachment_answer_system_prompt.txt` : 첨부 텍스트 응답용 경량 prompt
- 그 외 project / review / evidence 추출 관련 프롬프트

### tools/
- `ollama_client.py` : Ollama 호출
- `text_embedding.py` : 임베딩 생성 및 cosine similarity 비교

---

## 5. 현재 사용 모델 / 유사도 기준

### LLM
- 기본값: `qwen2.5:3b`
- 실제 사용은 UI에서 모델 선택 가능
- 로컬 환경에 따라 `gemma3:1b` 같은 경량 모델을 선택 가능

### Embedding
- 현재 기본 임베딩 모델: `intfloat/multilingual-e5-small`
- 비교 방식: cosine similarity

### Topic routing 기본 기준
- active topic 유지 threshold: `0.73`
- existing topic attach threshold: `0.78`

이 값들은 고정 진리가 아니라, 실제 사용 경험을 통해 계속 조정 가능한 운영값입니다.

---

## 6. 실행 방법

### 6-1. Python 가상환경

#### Git Bash
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

#### PowerShell
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 6-2. Ollama 준비

Ollama가 설치되어 있어야 합니다.

예:
```powershell
irm https://ollama.com/install.ps1 | iex
ollama --version
```

기본 모델 예시:
```bash
ollama pull qwen2.5:3b
ollama pull gemma3:1b
ollama pull llama3.2:3b
ollama pull gemma3:4b
```

### 6-3. 서버 실행

```bash
python -m uvicorn app.api:app --reload
```

브라우저:
```text
http://127.0.0.1:8000/ui
```

---

## 7. 사용 흐름

### 일반 채팅
- 일반 대화는 Orchestrator를 통해 처리됩니다.
- 응답 생성 후, update plan과 extraction policy를 거쳐 memory를 갱신합니다.
- 이 과정에서 active topic 유지/attach/create가 동작합니다.

### 첨부 텍스트
- 텍스트 첨부는 preview-only가 아니라 **update-first** 방향입니다.
- source 저장 → relevant passage 선택 → evidence 추출 → topic attach/create → memory sync → 자연어 답변 순으로 처리됩니다.

### ZIP artifact / project
- ZIP은 project 단위 artifact로 취급됩니다.
- file / chunk / review / evidence가 `project_id` 기준으로 관리됩니다.
- 같은 `project_id` 안에서 project 질문과 profile evidence 추출이 함께 일어날 수 있습니다.

---

## 8. 현재 중요한 한계

### 8-1. 첨부 텍스트 / artifact 경로 정렬은 아직 진행 중
일반 채팅의 topic routing은 많이 들어왔지만,
첨부 텍스트·artifact 경로는 아직 더 정교한 통일이 필요합니다.

### 8-2. confirmed / candidate / general 경계는 계속 다듬는 중
현재도 동작은 하지만, 경계 기준이 아직 완전히 고정된 것은 아닙니다.

### 8-3. correction 재구성은 더 확장될 여지가 있음
현재는 profile/summary 재구성이 중심이고,
향후에는 topic 수준의 merge / split / rebuild가 더 강화될 수 있습니다.

### 8-4. 속도 병목은 아직 존재함
현재 병목은 주로:
- 로컬 CPU 추론 속도
- 프롬프트 길이
- 응답 길이
- topic 생성 시 LLM 호출

쪽에 있습니다.

따라서 MK4는 멀티스레딩보다 먼저,
- 불필요한 호출 수 줄이기
- retrieval budget 줄이기
- prompt 경량화
를 우선적으로 택하고 있습니다.

### 8-5. `trusted_search`는 아직 stub
향후 확장 예정이지만 현재는 핵심 흐름에 들어가지 않습니다.

---

## 9. 현재 개발 원칙

현재 MK4를 손볼 때의 원칙은 다음과 같습니다.

- 오래된 ZIP 스냅샷이 아니라 **현재 작업본 기준**으로 계속 업데이트한다.
- topic은 문자열이 아니라 객체로 다룬다.
- 규칙 기반 topic 분류보다, **의미 기반 attach/create**를 우선한다.
- `project_id`는 제거하지 않고, artifact 출처 축으로 유지한다.
- general은 저장하되 매 턴 주입하지 않는다.
- confirmed도 절대 진실이 아니라 **현재 모델의 가설적 사용자상**으로 취급한다.
- correction이 오면, 과거 profile도 언제든 깨고 다시 만든다.
- 구조를 바꾼 뒤에는 반드시 레거시 참조를 지워서, 가독성과 유지보수를 같이 확보한다.

---

## 10. 앞으로 우선순위가 높은 작업

현재 기준 우선순위는 대략 이렇습니다.

1. 첨부 텍스트 / artifact 경로를 topic router 철학에 더 깊게 맞추기
2. confirmed / candidate / general 경계를 전 경로에서 일관되게 만들기
3. correction 기반 재구성을 topic 수준까지 확장하기
4. 새 topic 생성 후처리를 더 정교하게 만들기
5. retrieval budget 2차 축소
6. 실제 속도 / 품질 측정 루프 만들기
7. 남은 레거시/미사용 코드 추가 정리

---

## 11. DB 관련 주의

운영 DB 기본 경로는 다음입니다.

```text
data/memory.db
```

오래된 테스트 DB나 ZIP 안 과거 스냅샷 DB와 혼동하지 않는 것이 중요합니다.

---

## 12. 이 프로젝트가 지향하는 것

MK4는 “정답을 빨리 말하는 모델”보다,
**나를 일관되게 이해하고, 틀리면 다시 고치며, 시간이 지날수록 더 나에게 맞아지는 모델**을 지향합니다.

그래서 이 프로젝트는 단기 데모 완성보다,
- 설계 일관성
- 재구성 가능성
- 근거 기반 profile 형성
- 로컬 환경에서 실제로 굴러가는 구조

를 더 중요하게 봅니다.
