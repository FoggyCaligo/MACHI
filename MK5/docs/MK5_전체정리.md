# MK5 전체 정리

## 1. 한 문장 정의
MK5는 **입력을 의미 단위로 분해해 하나의 세계 그래프에 누적하고, 그 그래프의 국부 활성화와 현재 의도 위에서 사고를 전개한 뒤, 마지막에만 언어화하는 인지형 대화 시스템**이다.

핵심은 “좋은 답변을 내는 모델”이 아니라,
**그래프 형성 → 활성화 → 충돌 감지 → trust/revision → intent snapshot → explanation conclusion → action layer → verbalization**
을 분리하는 데 있다.

---

## 2. MK4와의 관계
MK4의 중심은 revisable memory substrate였다.
MK5의 중심은 **세계 그래프 기반 판단**이다.

즉:
- MK4 = evidence / memory / correction 중심
- MK5 = graph / activation / intent / conclusion 중심

둘은 단절이라기보다,
**저장층 중심에서 판단층 중심으로 무게중심이 올라간 관계**다.

발표는 MK4로 가고, MK5는 그 다음 단계의 방향성으로 설명하는 것이 현재 전략상 가장 적절하다.

---

## 3. 현재 확정된 철학

### 3-1. 세계 그래프는 하나다
- user / assistant / search / file 입력을 별도 기억창고로 떼지 않는다.
- 모두 하나의 세계 그래프에 들어간다.
- 다만 **출처(source/provenance)** 와 **claim_domain** 은 별도 축으로 저장한다.

즉,
- 정보는 **대상(entity)** 에 종속되고
- 그 정보가 어디서 왔는지는 **출처 축**으로 관리한다.

이 방향이 중요한 이유는,
‘사용자 정보’와 ‘외부 세계 정보’를 구조적으로 아예 다른 저장소로 나누기보다,
**같은 그래프 안에서 다른 신뢰정책과 검증정책을 적용하는 편이 더 일관되기 때문**이다.

### 3-2. 노드는 문장이 아니라 재사용 가능한 의미 단위다
- 원문 전체는 provenance로 남는다.
- 그래프에는 의미블록 / 개념 단위가 들어간다.
- 문장을 통째로 기억하는 것이 아니라, 재사용 가능한 단위를 누적한다.

### 3-3. 설명형 conclusion이 본체다
- 본체는 항상 `CoreConclusion`
- `activated_concepts` / `key_relations`는 그래프 참조다.
- 행동형 지시는 `DerivedActionLayer`로 얇게 파생된다.

### 3-4. 기본은 구조 보존이다
- 새 입력이 들어왔다고 기존 구조를 바로 부수지 않는다.
- 반복 충돌과 trust 하락이 누적될 때만 revision을 검토한다.

### 3-5. 언어화는 사고가 아니다
- verbalizer는 이미 만들어진 결론을 한국어 문장으로 바꾸는 층이다.
- 언어모델이 그래프를 대신해 사고하거나 구조를 덮어쓰면 안 된다.

### 3-6. fallback은 줄이고, 오류는 오류처럼 드러낸다
- 템플릿 답변 fallback은 금지한다.
- intent가 없으면 내부 추정으로 때우지 않고 오류가 나야 한다.
- 검색 실패는 “결과 없음”으로 숨기지 말고 transport failure로 드러나야 한다.

---

## 4. 현재 구현 구조

### 4-1. 저장 계층
- SQLite schema / repositories / unit of work 연결됨
- `chat_messages / nodes / edges / graph_events / node_pointers` 사용
- repository는 CRUD가 아니라 그래프 엔진 기준 질의 중심

### 4-2. 입력 인지 및 ingest
- `InputSegmenter`가 입력을 의미블록으로 분해
- `GraphIngestService`가 node / edge / pointer / event 생성
- source-aware trust policy 반영
- partial reuse pointer 생성

### 4-3. 활성화
- `ActivationEngine`이 현재 입력 기준으로 `ThoughtView` 생성
- seed block → seed node → local node / edge / pointer 수집
- `PatternDetector`가 패턴 감지

### 4-4. 사고 계층
현재 주요 축:
- `ContradictionDetector`
- `TrustManager`
- `StructureRevisionService`
- `IntentManager`
- `ConclusionBuilder`

현재 순서:
1. 충돌 감지
2. trust 하락
3. revision candidate 표시
4. revision review
5. 필요 시 shallow merge / edge deactivation
6. intent snapshot 결정
7. explanation 중심 conclusion 생성

### 4-5. revision / merge
현재 merge 정책:
- ingest 직후 자동 merge 안 함
- **revision 단계에서만 merge**
- threshold는 비교적 얕게
- 실제 merge 허용 범위는 duplicate-like node로 보수적으로 제한

### 4-6. verbalization
- `Verbalizer`
- `OllamaVerbalizer`
- `TemplateVerbalizer`는 사용자 응답 fallback이 아니라 사실상 금지/오류 성격

현재 목표는
**graph-centric 내부 판단을 user-facing 문장으로 번역하되,
node/edge/trust/revision 같은 내부 용어를 본문에 직접 노출하지 않는 것**이다.

### 4-7. 검색
현재 search 계층은 이미 존재한다.
다만 최신 zip 기준으론 **아직 위키피디아 중심 backend** 성격이 강하고,
중간 대화에서 설계한 확장형 trusted_search는 아직 완전히 기준본에 정착되지 않았다.

즉:
- search need evaluator 있음
- question slot planner 있음
- search query planner 있음
- sidecar 있음
- 그러나 retrieval 품질과 backend 확장성은 여전히 미완성

---

## 5. 지금까지 확정된 중요한 설계 변화

### 5-1. normalized_value fallback 제거
과거에는 direct node reuse에서
`address_hash` 실패 시 `normalized_value`로 다시 재사용하는 fallback이 있었는데,
이건 MK5 core 철학과 맞지 않았다.

현재 방향:
- **node 재사용은 address_hash 기준이 우선**
- 문자열 기반 우회 재사용은 제거

### 5-2. intent fallback 제거
과거에는 intent snapshot이 없으면 conclusion builder가 그래프 상태를 몇 가지 규칙으로 읽어 intent를 때우는 fallback이 있었다.

현재 방향:
- intent 없으면 내부 추정으로 메우지 않음
- 명시적으로 오류

### 5-3. template fallback 금지
과거의 “모델 실패 시 템플릿으로라도 대답”은 폐기

현재 방향:
- 사용자 답변 fallback 금지
- 모델 실패는 오류로 드러냄

### 5-4. stopword / 강제 statement fallback 제거
`InputSegmenter` 쪽의 stopword 하드코딩과,
아무 블록도 못 만들면 statement를 강제 생성하던 fallback은 제거 방향으로 정리됨.

---

## 6. search에 대해 지금까지 정리된 최종 방향

### 6-1. 문자열 휴리스틱 기반 검색은 지양
- “검색”, “해줄래”, “우선” 같은 메타 단어로 search를 결정하면 안 된다.
- 질문 표면 형태보다 현재 활성 그래프와 결손을 봐야 한다.

### 6-2. 질문 전체 단위 search보다 결손 슬롯 단위 search
이게 지금까지 대화에서 가장 중요한 진전이다.

이전 방향:
- 질문 전체를 보고 search 할지 말지 크게 한 번 판단
- 전체 질문 기준 query 생성

현재 지향 방향:
1. 질문에서 **entity / aspect slot** 추출
   - 예: `판금갑옷`, `찰갑`, `사슬갑옷`, `미늘갑옷`, `가죽갑옷`
   - 예: `구조`, `방어력`, `기동성`
2. 현재 그래프가 각 슬롯을 얼마나 커버하는지 검사
3. **비어 있는 slot만 국소적으로 search**
4. 결과를 그래프에 넣고 다시 생각

즉 search 단위가
**question-level** 에서 **gap-level** 로 내려간다.

### 6-3. search need는 graph-first여야 한다
- 모델이 “필요하면 검색해라”를 자유롭게 결정하면 안 된다.
- search 필요 판단의 중심은 그래프/사고 계층에 있어야 한다.
- 모델은 search query planning, slot extraction, 질의 재구성 같은 보조 역할만 맡는 것이 맞다.

### 6-4. planner 실패 시 보수적으로 search 쪽으로 기울어야 한다
이건 최근 버그를 통해 확인된 교훈이다.

잘못된 방식:
- slot planner 실패
- 그런데 기존 그래프 일부가 있으니 sufficient 판정
- 결과적으로 hallucination

현재 방향:
- multi-entity / multi-aspect 질문에서 planner 실패 시
- **fail-open to search**
- 즉, “검색 필요 false”로 바로 떨어지지 않게 해야 한다.

### 6-5. 검색 실패와 결과 없음을 구분해야 한다
- 404, timeout, DNS failure, provider failure
- 결과 0건

이 둘은 다르다.
현재 목표는 search debug에서:
- `provider_errors`
- `error: search_transport_failure`
- `result_count`
를 분리해서 보여주는 것이다.

### 6-6. grounded / missing 항목 추적
지금은 질문 전체가 아니라 **어떤 항목이 근거를 가졌는지**가 중요하다.
그래서 search 이후에는 최소한 아래를 계산해야 한다.

- `grounded_terms`
- `missing_terms`
- 나아가면 `missing_aspects`

이게 있어야 verbalizer가 빈 부분을 자연스럽게 메우지 못한다.

---

## 7. conflict 처리에 대해 확정된 좋은 방향
최근 대화에서 나온 중요한 아이디어:

> 기존 그래프와 충돌 시,
> search가 가능한 대상이면 external search로 더블체크하고,
> 확인되면 trust를 올리고,
> trust 상승에 따라 graph update 조건이 충족되면 구조를 갱신한다.

이 방향은 좋다.
다만 지금은 “사용자 정보 vs 세계 정보”로 나누기보다,
**정보는 대상(entity)에 종속되고, 출처와 검증 가능성이 별도 축으로 붙는 구조**로 보는 편이 더 일관적이라는 점이 함께 확정됐다.

즉:
- `가죽갑옷`에 대한 정보도
- `사용자`에 대한 정보도
모두 entity에 귀속될 수 있다.

다만:
- search 가능성
- corroboration 가능성
- provenance
은 각각 다르다.

즉 policy는
**대상 중심 + 출처/검증 축 별도**
로 가는 것이 현재 가장 적절하다.

---

## 8. 지금까지 실제로 드러난 버그들

### 8-1. 새 entity가 search coverage에서 빠지는 버그
예:
- 기존 갑옷 비교 맥락이 어느 정도 있음
- 질문에 `가죽갑옷` 추가
- 그런데 evaluator가 기존 그래프만 보고 sufficient 판정
- 결과적으로 search false + hallucination

교훈:
- scope는 현재 질문의 모든 anchor entity를 포함해야 한다.
- limit 때문에 뒤에 붙은 새 entity가 잘리면 안 된다.

### 8-2. slot planner invalid JSON
- planner가 JSON을 깨뜨리면 전체 slot coverage가 무력화됨
- 그런데 failure handling이 잘못되면 그대로 “sufficient”로 가버릴 수 있음

교훈:
- planner는 `response_format='json'`을 쓰고
- 그래도 실패하면 lenient parse를 시도하고
- 그래도 안 되면 fail-open to search

### 8-3. search debug 계약 혼란
- `query_triggered`가 planning attempted와 actual search execution을 함께 의미하면 안 된다.

교훈:
- `planning_attempted`
- `query_triggered`
를 분리해야 한다.

### 8-4. grounded evidence 없이도 모델이 단정적으로 답하는 문제
예:
- `찰갑` 검색 결과가 없는데도 모델이 `찰갑은 …`이라고 설명

교훈:
- 이건 시스템 계약상 hallucination 취급이 맞다.
- verbalization 층에서 missing term이 있으면 단정을 더 강하게 금지해야 한다.

---

## 9. 최신 zip 기준 placeholder / 미완성 상태 정리

### 9-1. 실제 placeholder로 남아 있는 곳
- `tools/response_runner.py`
- `app/orchestrator.py`
- `app/routes/chat.py`
- `core/update/graph_commit_service.py`
- `core/update/edge_update_service.py`
- `core/verbalization/llm_verbalizer.py`
- `core/verbalization/meaning_preserver.py`

### 9-2. 이미 placeholder를 벗어난 것
- `tools/ollama_client.py`
- `tools/prompt_loader.py`
- `core/thinking/intent_manager.py`
- `core/update/node_merge_service.py`
- `core/update/pointer_rewrite_service.py`
- `core/search/question_slot_planner.py`
- `core/search/search_need_evaluator.py`
- `core/search/search_query_planner.py`
- `core/search/search_sidecar.py`

### 9-3. placeholder는 아니지만 아직 초기형인 것
- search backend 전체
- input segmenter
- verbalization groundedness 제어
- post-search synthesis

---

## 10. 지금 시점의 우선순위

### 최우선
1. **slot 기반 coverage / missing-slot search 안정화**
2. **search failure vs no-result 구분 고정**
3. **missing term / missing aspect가 있으면 hallucination 억제 강화**

### 그 다음
4. **trusted_search backend 확장**
5. **conflict → external verification → trust 상승 → graph update** 정책 추가
6. **post-search re-think / synthesis 강화**

### 중기
7. `graph_commit_service.py` 실구현
8. `edge_update_service.py` 실구현
9. `meaning_preserver.py` 또는 동등한 의미 보존 점검 계층 추가

### 정리/관리
10. docs와 실제 코드 상태 다시 맞추기
11. requirements / run path / Windows 실행 가이드 재점검

---

## 11. 다음 채팅에서 바로 이어갈 수 있는 한 줄 요약
“MK5는 현재 그래프 기반 thought loop와 revision 단계 shallow merge, intent snapshot, search sidecar까지 연결돼 있고, 지금 가장 중요한 작업은 질문 전체가 아니라 **그래프의 결손 슬롯만 국소 search**하는 구조를 안정화하는 것이다.”
