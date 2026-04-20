# MK5 전체정리 (마스터 문서)

업데이트: 2026-04-20

## 1. 현재 정체성
MK5는 "그래프 중심 인지 시스템"이다.  
LLM은 구조 판정/제안/언어화에 참여하는 하위 모듈이고, 장기 상태와 판단 근거의 중심은 그래프다.

## 2. 실행 파이프라인
1. User ingest
2. Activation (`ThoughtView`)
3. Think→Search 루프 (최대 3회)
   - Think (contradiction → trust update → revision)
   - SearchScopeGate: query vs 활성 노드 임베딩 코사인 유사도로 검색 필요 여부 판정
   - 검색 불필요 → 루프 종료 / 검색 필요 → 검색 결과 Ingest → Re-Activation → 반복
   - 최대 횟수 도달 시 최종 Think 1회 추가
4. ConclusionView 구성
   - 사용자 입력 핵심 키워드(topic_terms) 기반 그래프 서브구조 룰 기반 선별
   - Verbalization 계층이 참조하는 유일한 결론 구조
5. Verbalization
6. Assistant ingest

## 3. Edge-first 기준
- `edge_family`: `concept | relation`
- `connect_type`: `flow | neutral | opposite | conflict`
- `relation_detail`: 보조 정보(note/provenance/proposal/scope)

핵심 원칙:
- 구조 변경은 즉시가 아니라 누적으로 실행
- revision은 marker edge + 규칙 테이블로 결정
- connect type 확장은 proposal 누적 후 승격

## 4. Revision 체계
- marker edge 종류:
  - `conflict_assertion`
  - `revision_pending`
  - `deactivate_candidate`
  - `merge_candidate`
- 실행 서비스:
  - `StructureRevisionService`
  - `RevisionExecutionRule` (family/connect_type 기준 분기)
- runtime override:
  - `REVISION_RULE_OVERRIDES_PATH`
  - `REVISION_RULE_PROFILE`
  - `REVISION_RULE_OVERRIDES_STRICT`

## 5. LLM 호출 구조

| 컴포넌트 | 종류 | 호출 조건 |
|---|---|---|
| SearchScopeGate | 임베딩 (nomic-embed-text) | 매 루프 회차 |
| QuestionSlotPlanner | Ollama LLM | 검색 필요 판정 시 |
| SearchCoverageRefiner | Ollama LLM | 검색 결과 있을 때만 |
| ModelEdgeAssertionService | Ollama LLM | 매 턴 |
| OllamaVerbalizer | Ollama LLM | 매 턴 |
| ModelFeedbackService | **제거됨** | — |

최소(검색 불필요): **2회** / 최대(검색 3회 루프): **8회**

## 6. 최근 완료 항목
- temporary edge 정리(topic shift 기반)
- model edge assertion 연계
- connect type promotion 강화
- revision rule analytics/tuner/report 추가
- override 자동 적용 도구/스케줄러 추가
- Think→Search 루프 구조화 (최대 3회, for-else 패턴)
- 루프 내 Ollama 타임아웃 3배 상향
- ConclusionView 도입: CoreConclusion(루프 내부 전용)과 분리된 Verbalization 결론 구조
  - `core/entities/conclusion_view.py`
  - `core/thinking/conclusion_view_builder.py` (룰 기반 노드/엣지 선별)
- ModelFeedbackService 제거 (LLM 1회 절감)
- SearchScopeGate LLM → 임베딩+코사인 교체
  - `core/search/search_scope_gate.py` 전면 재작성
  - `tools/ollama_client.py`: `embed()` 메서드 추가
  - 기본 모델: `nomic-embed-text`, 임계치: 0.65

## 7. 운영 자동화
- 분석:
  - `tools/revision_rule_report.py`
- 적용:
  - `tools/revision_rule_apply_overrides.py`
- 주기 실행(Windows):
  - `tools/run_revision_rule_override_job.ps1`
  - `tools/setup_revision_rule_scheduler.ps1`

## 8. 운영 전제조건
```bash
ollama pull nomic-embed-text
```
- `EMBEDDING_MODEL_NAME` 환경변수로 대체 모델 지정 가능
- `SCOPE_GATE_SIMILARITY_THRESHOLD` 환경변수로 임계치 조정 (기본 0.65)
- 미설치 시 ScopeGate fail-open → SlotPlanner 경로로 진행

## 9. 현재 남은 우선과제
1. ConclusionViewBuilder 키워드 매칭 정교화 (의미적 유사도 확장)
2. E2E 회귀 확대(루프 3회 + ConclusionView 흐름)
3. override 프로필 전환 A/B 운영 가이드
4. Linux cron 운영 스크립트 추가

## 10. 문서 체계
- 마스터: `docs/guid/MK5_전체정리.md`
- 아키텍처 상세: `docs/architecture/*`
- 전략: `docs/guid/MK5_검색_및_검증_전략.md`
- 핸드오프: `docs/handoff/MK5_handoff.md`
- 단기 실행: `docs/todo/현재작업.txt`
