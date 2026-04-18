# MK5 파일 단위 변경 계획서

기준본: `MK5 (2).zip` sync 기준

## 결론
이번 리팩토링은 **바로 코드 작업에 들어가면 위험한 편**이다.
이유는 단순 버그 수정이 아니라, **핫패스 순서 자체를 재배선**해야 하기 때문이다.

현재 코드의 실제 흐름:
1. user ingest
2. activation 1차
3. thinking 1차
4. search
5. search ingest
6. activation 2차
7. thinking 2차
8. verbalization
9. assistant answer ingest

목표 흐름:
1. 입력 수신
2. 의미 단위 분해(LLM + 얇은 deterministic fallback)
3. direct access
4. usable하지 않은 단위 자동 search
5. search batch ingest + 약한 edge 연결
6. activation 1회
7. think 1회
8. verbalization
9. assistant snapshot만 저장 (full answer ingest 제거)

## 왜 바로 코드 작업이 위험한가
- `ChatPipeline.process()`의 단계 순서를 크게 바꿔야 함
- `GraphIngestService`, `ActivationEngine`, `SearchSidecar`, `ThoughtEngine`, `Verbalizer`가 동시에 영향을 받음
- 현재는 입력 block 분해를 ingest/activation에서 중복 수행 중이라, 의미 단위 객체를 재사용하는 쪽으로 바꿔야 함
- assistant answer ingest 제거 시 debug/persistence/test가 같이 영향받음
- 현재 테스트 대부분이 기존 순서(think 전 search 없음 / assistant ingest 존재)를 전제할 수 있음

따라서 한 턴에 안전하게 끝내려면, **먼저 파일 단위 변경 계획을 고정한 뒤** 그 계획대로 한 번에 작업하는 것이 맞다.

---

## 변경 원칙
- 새 서비스 레이어를 덕지덕지 추가하지 않는다.
- 기존 파일을 수정/축소/이동시키는 방식으로 간다.
- `mention-only` 노드는 허용하되, direct access 성공으로 치지 않는다.
- direct access 성공 조건은 `node exists`가 아니라 `node is usable for this question`이다.
- 현재 입력은 접근 키이지 grounding 근거가 아니다.
- search는 think 전에 끝나야 한다.
- assistant full answer ingest는 제거한다.

---

## Phase 1. 입력 분해 / direct access 기준 재정의

### 1-1. `core/cognition/input_segmenter.py`
목표:
- 현재 정규식 기반 분해는 유지하되, **LLM이 후처리할 후보 목록**을 만들도록 역할 축소
- 문장 노드를 늘리지 않도록, 출력은 여전히 얇은 candidate 수준 유지

변경:
- 현재 `split_sentences()` / `segment()` 유지
- 출력 block에 `candidate_order`, `sentence_role` 정도의 경량 metadata 추가 가능
- 여기서 search/query focus를 직접 만들지는 않음

리스크:
- 낮음

### 1-2. `core/cognition/meaning_block.py`
목표:
- LLM 해석 결과를 얹을 수 있도록 meaning unit metadata 확장

변경:
- `role_in_query`, `importance`, `freshness_kind` 같은 선택적 metadata 필드 수용

리스크:
- 낮음

### 1-3. `app/chat_pipeline.py`
목표:
- 입력 직후 **LLM 기반 의미 해석 1회**를 수행하고 그 결과를 이후 단계 전체에 재사용

변경:
- 현재 `request.message`를 ingest 전에 `InputSegmenter`로 candidate 분해
- candidate list를 LLM에 넘겨 다음 정보 추출:
  - current_intent
  - primary_keywords
  - secondary_keywords
  - ignore_for_search
  - freshness_kind per keyword
- 이 결과를 `ChatPipeline.process()` 내부 로컬 변수로 유지
- 이후 ingest/search/activation/thinking에 재사용

리스크:
- 중간
- 새로운 별도 엔진을 만들기보다, `ChatPipeline` 내부 private helper로 제한

---

## Phase 2. search-before-think로 순서 재배선

### 2-1. `app/chat_pipeline.py`
목표:
- 현재 순서
  - ingest → activation 1차 → thinking 1차 → search → search ingest → activation 2차 → thinking 2차
- 목표 순서
  - ingest → direct access/search completion → activation 1회 → thinking 1회

변경:
- thinking 1차 제거
- search 이전 activation 제거
- search 후 activation/thinking만 남김
- search ingest는 batch ingest 성격으로 묶는 방향 검토

리스크:
- 높음
- 이번 리팩토링의 핵심 파일

### 2-2. `core/search/search_need_evaluator.py`
목표:
- 그래프 총량 기반 흔적 제거
- 의미 단위별 usable grounding 평가기로 전환

변경:
- 입력: `thought_view` 중심이 아니라 **LLM 해석 결과(primary keywords / freshness labels)**를 받도록 수정
- 평가 기준:
  - node_missing
  - mention_only
  - grounded_but_stale
  - grounded_but_insufficient
  - grounded_and_usable
- `current_root_event_id` 생성 노드는 grounding 제외

리스크:
- 높음

### 2-3. `core/search/search_query_planner.py`
목표:
- concept 결합 없이, **usable하지 않은 keyword마다 개별 query 자동 발행**

변경:
- 입력을 `missing_terms`가 아니라 `unusable_keywords`로 단순화
- freshness_kind에 따라 query priority 조정만 수행
- query plan은 keyword 단위 개별 발행만

리스크:
- 중간

### 2-4. `core/search/search_sidecar.py`
목표:
- thought 이후 보조 search가 아니라, **graph completion 단계**로 역할 전환

변경:
- `run()`이 `message + thought_view + conclusion`이 아니라
  `message + analyzed_keywords + access_results`를 입력으로 받게 수정
- search 결과 반환을 최대한 단순화
- 가능하면 batch ingest 친화적으로 정리

리스크:
- 높음

---

## Phase 3. activation 1차 제거 / 중복 segmentation 제거

### 3-1. `core/activation/activation_engine.py`
목표:
- activation은 **search completion 이후 1회만** 돌리기
- 입력 segmentation 중복 제거

변경:
- `ActivationRequest`에 `blocks` 또는 `meaning_units`를 직접 전달
- 내부에서 `InputSegmenter.segment()`를 다시 호출하지 않도록 수정
- `_resolve_seed_nodes()`는 전달받은 blocks로만 작동

리스크:
- 높음

### 3-2. `core/activation/thought_view_builder.py`
목표:
- search 이후의 한 번짜리 activation 기준으로 thought view 생성

변경:
- metadata 정리
- `current_root_event_id` 및 keyword focus만 유지
- 이전 단계 흔적 정리

리스크:
- 중간

---

## Phase 4. think 1회 구조로 축소

### 4-1. `core/thinking/thought_engine.py`
목표:
- think는 search 후 1회만 수행

변경:
- contradiction → trust → revision → concept differentiation → intent manager → conclusion 유지
- pre-search thought 호출 경로 제거

리스크:
- 중간

### 4-2. `core/thinking/intent_manager.py`
목표:
- 주제 따라가기를 의미 단위 해석 결과와 결합

변경:
- current topic terms를 activation 결과 + LLM primary keywords로 보강
- 자기소개/배경 설명보다 query focus를 더 우선하도록 조정

리스크:
- 중간

### 4-3. `core/thinking/concept_differentiation_service.py`
목표:
- 핵심 concept와 주변 concept를 더 잘 분리

변경:
- primary/secondary keyword 우선권 반영
- mention-only 노드를 중심 concept로 승격하지 않도록 조정

리스크:
- 중간

### 4-4. `core/thinking/conclusion_builder.py`
목표:
- explanation summary가 "현재 그래프에 많은 것"이 아니라 "이번 질문 초점"을 따르도록 정리

변경:
- activated_concepts 요약 축소
- query focus 기반 explanation_summary 생성

리스크:
- 중간

---

## Phase 5. verbalization 계약 강화

### 5-1. `core/verbalization/verbalizer.py`
목표:
- grounded/search evidence가 없으면 **LLM 자유 생성 금지**

변경:
- boundary response 조건 강화
- `mention-only`만 있는 경우도 근거 없음으로 간주

리스크:
- 낮음

### 5-2. `core/verbalization/action_layer_builder.py`
목표:
- search evidence가 있으면 evidence-first answer를 강제

변경:
- grounded + evidence 있음 → 설명 모드
- grounded 없음 → 경계 응답 모드

리스크:
- 낮음

### 5-3. `core/verbalization/ollama_verbalizer.py`
목표:
- prompt에 snippet보다 passage/evidence 상태를 더 직접 반영

변경:
- search_status 단순화
- evidence_available / coverage_unconfirmed / freshness hints 반영

리스크:
- 낮음

---

## Phase 6. assistant answer ingest 제거

### 6-1. `app/chat_pipeline.py`
목표:
- assistant full answer ingest 제거

변경:
- 현재 `GraphIngestService.ingest(role='assistant', ...)` 호출 삭제
- 대신 lightweight snapshot만 저장
  - topic_terms
  - tone_hint
  - intent snapshot
- 이 snapshot은 chat_message metadata 또는 별도 lightweight path에 저장

리스크:
- 높음
- 최근 대화 회수 로직과 debug 영향 있음

### 6-2. `core/activation/activation_engine.py`
목표:
- recent_memory_messages가 assistant full answer가 아니라 snapshot 기반으로도 충분히 작동하게 조정

리스크:
- 중간

---

## Phase 7. 문서 업데이트

### 7-1. 업데이트 대상 문서
- `SLIMMED_RUNTIME.md`
- `docs/runtime_change_summary.md`
- `docs/runtime_philosophy_and_contract.md`
- `docs/architecture/thought_flow.md`
- `docs/guid/MK5_about_search.md`
- `docs/guid/MK5_master_doc.md`

### 7-2. 새 문서 또는 교체 필요
- `docs/refactor/MK5_refactor_file_plan.md`
- `docs/refactor/MK5_refactor_runtime_target.md`

---

## 삭제 또는 완전 비활성 후보

### 우선 제거 대상
- assistant full answer ingest 경로
- activation 1차 호출 경로
- thinking 1차 호출 경로
- activation 내부 재-segmentation

### 남겨도 되지만 정리 필요
- `subgraph_pattern.py` / pattern repository 계열 (현재 런타임 미사용이면 후순위)
- 예전 search planner prompt 파일 (실사용 없으면 제거)

---

## 구현 순서 권장
1. `ChatPipeline.process()` 재배선
2. `SearchNeedEvaluator` usable grounding 기준 전환
3. `SearchSidecar` 입력/역할 단순화
4. `ActivationEngine` 재-segmentation 제거
5. `ThoughtEngine` 1회만 호출되게 정리
6. `Verbalizer` hard boundary 강화
7. assistant ingest 제거
8. 문서 일괄 업데이트

---

## 실행 전략 제안
이번 리팩토링은 **한 턴에 전부 바로 구현하면 위험한 편**이다.
가장 안전한 방식은 아래 두 단계다.

### Step A. 순서 재배선만 먼저
- think/search 순서 정상화
- activation 1차 제거
- assistant ingest 제거
- 기존 deterministic segmentation 유지

### Step B. 의미 분해 LLM 도입
- candidate 기반 LLM 후처리
- freshness 라벨링
- usable grounding 세분화

이렇게 가면 런타임 구조를 먼저 안정화하고, 그 다음 LLM 해석층을 올릴 수 있다.

## 최종 판단
**바로 코드 작업 진행은 위험한 편이다.**
이유는 단일 버그 수정이 아니라, 여러 파일에 걸친 실행 순서 변경이기 때문이다.
따라서 이번 턴 기준으로는 **파일 단위 변경 계획서를 먼저 고정하는 것이 맞다.**
