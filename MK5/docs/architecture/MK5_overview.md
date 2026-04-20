# MK5 Overview

업데이트: 2026-04-20

## 한 줄 요약
MK5는 입력을 그래프에 적재하고, 활성 그래프에서 사고/판정을 수행한 뒤, 결론만 언어화하는 edge-first 파이프라인이다.

## 파이프라인
1. Ingest
   - `GraphIngestService`가 node/edge/pointer/event를 기록
2. Activation
   - `ActivationEngine`이 현재 질의 중심 `ThoughtView` 구성
3. Think→Search 루프 (최대 3회, `_THINK_SEARCH_MAX_LOOPS`)
   - `ThoughtEngine`: contradiction 감지 / trust·pressure 갱신 / marker edge 누적 / revision 실행
   - `SearchSidecar`: 검색 필요 없으면 break, 결과 있으면 Ingest → Re-Activation → 반복
   - 최대 횟수 도달 시 for-else로 최종 Think 1회 추가
   - `CoreConclusion`은 루프 내부 전용 중간 산물 (SearchSidecar 방향 결정에 사용)
4. ConclusionView 구성
   - `ConclusionViewBuilder`가 최종 ThoughtView/ThoughtResult를 받아 룰 기반으로 구성
   - 사용자 입력 핵심 키워드(topic_terms) 기준으로 노드/엣지 선별
   - Verbalization 계층이 참조하는 유일한 결론 구조 (CoreConclusion 대체)
5. Verbalization
   - `ConclusionView`를 사용자 응답으로 언어화
6. Assistant ingest
   - 최종 응답도 다시 그래프에 적재

## Edge-first 상태
- `edge_family/connect_type/relation_detail` 3축으로 의미를 표현한다.
- connect type 제안은 즉시 스키마 확장 대신 proposal로 누적 후 승격한다.
- temporary edge는 session/topic 전환 정책으로 정리한다.

## LLM 호출 구조 (Ollama 모델 기준)

| 컴포넌트 | 종류 | 호출 조건 |
|---|---|---|
| SearchScopeGate | 임베딩 모델 (nomic-embed-text) | 매 루프 회차 |
| QuestionSlotPlanner | Ollama LLM | ScopeGate가 검색 필요로 판정한 경우 |
| SearchCoverageRefiner | Ollama LLM | 검색 결과가 있을 때만 |
| ModelEdgeAssertionService | Ollama LLM | 매 턴 |
| OllamaVerbalizer | Ollama LLM | 매 턴 |
| ModelFeedbackService | **제거됨** | — |

최소 LLM 호출 (검색 불필요): **2회** (EdgeAssertion + Verbalizer)
최대 (검색 3회 루프): **8회** (SlotPlanner×3 + CoverageRefiner×3 + EdgeAssertion + Verbalizer)

## 운영 튜닝
- revision 규칙은 override 파일로 런타임에서 조정 가능
- 추천/적용 도구:
  - `tools/revision_rule_report.py`
  - `tools/revision_rule_apply_overrides.py`
- 자동화:
  - `tools/run_revision_rule_override_job.ps1`
  - `tools/setup_revision_rule_scheduler.ps1`

## 운영 전제조건
```bash
ollama pull nomic-embed-text   # SearchScopeGate 임베딩 모델
```
- `EMBEDDING_MODEL_NAME` 환경변수로 대체 모델 지정 가능 (기본: `nomic-embed-text`)
- `SCOPE_GATE_SIMILARITY_THRESHOLD` 환경변수로 임계치 조정 가능 (기본: 0.65)
- 미설치 시 ScopeGate fail-open → `scope_gate_error` 노출 후 SlotPlanner 경로로 진행
