# MK5 Handoff

업데이트: 2026-04-20

## 이번 세션 핵심 변경 (2026-04-20) — LLM 호출 최소화

### ModelFeedbackService 제거
- 역할: 사용자 메시지 기준으로 기존 엣지에 support/conflict 투표 → trust 조정
- 제거 이유: ContradictionDetector + TrustManager가 이미 그래프 기반으로 동일 역할 수행, LLM 1회 절감
- 변경 파일: `app/chat_pipeline.py`, `config.py`
  - import/인스턴스/LLM 호출/graph_commit/debug 항목 모두 제거
  - `MODEL_FEEDBACK_*` config 3개 제거

### SearchScopeGate LLM → 임베딩+코사인 교체
- 기존: Ollama LLM 1회 호출 → "외부 검색 필요 여부" 판정
- 변경: 임베딩 모델(nomic-embed-text) 기반 코사인 유사도 판정 → LLM 호출 0회
- 판정 방식:
  - `query 임베딩` vs `활성 노드 텍스트 임베딩(max 30개)` 코사인 유사도 최댓값 계산
  - max_sim ≥ `SCOPE_GATE_SIMILARITY_THRESHOLD`(기본 0.65) → 그래프 내 답변 가능 → 검색 불필요
  - max_sim < threshold → 외부 근거 필요 → 검색 진행
- 활성 노드 없음 → 즉시 검색 필요로 판정
- fail-open: 임베딩 실패(모델 미설치 등) → `SearchScopeGateError` → `scope_gate_error` 노출 후 SlotPlanner 경로로 진행
- 변경 파일: `core/search/search_scope_gate.py`, `tools/ollama_client.py`, `config.py`, `core/search/search_sidecar.py`

#### 운영 전제조건
```bash
ollama pull nomic-embed-text
```
- `EMBEDDING_MODEL_NAME` 환경변수로 모델 변경 가능 (기본: `nomic-embed-text`)
- `EMBEDDING_TIMEOUT_SECONDS` (기본: 10s)
- `SCOPE_GATE_SIMILARITY_THRESHOLD` (기본: 0.65, 낮출수록 검색 더 자주 발생)

#### LLM 호출 횟수 변화
| 경로 | 이전 | 이후 |
|---|---|---|
| Ollama 모델, 검색 불필요 | 4회 (ScopeGate+FB+EA+Verb) | 3회 (EA+Verb, ScopeGate→임베딩) |
| 검색 1회 | 7회 | 5회 (SlotPlanner+CoverageRefiner+EA+Verb) |
| 검색 3회(max) | 13회 | 9회 |

- ModelFeedbackService(FB) 제거 효과: 모든 경로에서 -1회
- ScopeGate 임베딩 교체: Ollama LLM 횟수 추가 -1회 (임베딩 모델은 별도 경량 모델)

## 이번 세션 핵심 변경 (2026-04-20) — 파이프라인 구조

### Think→Search 루프 구조화
- `chat_pipeline.py`의 1회 고정 흐름을 최대 3회 루프(`_THINK_SEARCH_MAX_LOOPS`)로 교체
- Python `for-else` 패턴: break(검색 결과 없음) 시 정상 종료, 완주 시 최종 Think 1회 추가
- 루프 내 Ollama 관련 타임아웃 3배 상향 (QUESTION_SLOT_PLANNER, SEARCH_COVERAGE_REFINER, OLLAMA_TIMEOUT, REQUEST_TIMEOUT)
- 루프 밖 단일 실행 컴포넌트(Verbalizer, ModelEdgeAssertion) 타임아웃은 유지

### ConclusionView 도입 (MK1 원설계 복원)
- 배경: MK1에서 "결론 = 의도 필터링된 그래프 서브구조, 언어화는 그 다음"이 원설계였으나 MK5에서 누락
- 신규: `core/entities/conclusion_view.py`
- 신규: `core/thinking/conclusion_view_builder.py` (룰 기반)
  - 선별 기준: topic_terms 키워드 매칭 + trust_score ≥ 0.3 + 1-hop 이웃 확장
  - 엣지: 선별 노드 간 + connect_type ≠ 'conflict' + trust_score ≥ 0.3
- `CoreConclusion`: 루프 내부 전용으로 역할 격리 (SearchSidecar 방향 결정에만 사용)
- `ConclusionView`: Verbalization 계층 전체가 참조하는 유일한 최종 결론 구조
- 변경된 파일: `verbalizer.py`, `template_verbalizer.py`, `ollama_verbalizer.py`, `action_layer_builder.py`, `meaning_preserver.py`, `chat_pipeline.py`

## 이전 세션 핵심 변경 (2026-04-16)
- Edge-first 정책을 유지한 상태로 `RevisionExecutionRule` 기반 실행 규칙을 확장.
- conflict/opposite/connect_type 분기 규칙과 evidence 가중치 기반 게이트를 강화.
- `TemporaryEdgeService`로 topic shift 시 `session_temporary` edge 자동 정리 경로를 유지.
- `ModelEdgeAssertionService`/`ConnectTypePromotionService` 연계 구조를 계속 사용.
- edge 의미론 문자열에 대한 코어 실행 의존을 제거.
  - revision/contradiction/merge gate는 `edge_family + connect_type + purpose/status` 기반으로 동작.
  - marker 집계 키도 문자열 의미론 대신 `total_support/conflict_support` 축으로 전환.

## 신규: 독립 revision review 실행 경로
- `ThoughtEngine.run_revision_review(...)` 추가
- `ChatPipeline.run_internal_revision_review(...)` 추가
- API 추가: `POST /internal/revision-review`
  - 메시지 입력 없이 system/internal 트리거로 revision cycle을 독립 실행 가능
  - graph event `revision_review_cycle` 기록

## 신규 반영: revision rule override 자동 적용
- `app/chat_pipeline.py`가 시작 시 override JSON을 자동 로드해 `StructureRevisionService(rule_overrides=...)`에 주입.
- 설정 키:
  - `REVISION_RULE_OVERRIDES_PATH`
  - `REVISION_RULE_PROFILE`
  - `REVISION_RULE_OVERRIDES_STRICT`
- 동작:
  - strict=false(기본): override 파일이 깨져도 서비스는 계속 동작, 오류는 디버그에 노출.
  - strict=true: override 로드 실패를 런타임 오류로 즉시 처리.

## 디버그 노출
- `debug.revision_policy.profile`
- `debug.revision_policy.override_path`
- `debug.revision_policy.override_load_error`
- `debug.revision_policy.override_rule_count`
- `debug.revision_policy.overrides_loaded`
- `debug.search.need_decision.scope_gate_attempted`
- `debug.search.need_decision.scope_gate` (max_similarity, node_count, threshold 포함)
- `debug.search.need_decision.scope_gate_error`

## 테스트/검증 메모
- Windows 환경에서 `pytest` temp/cache 디렉터리 권한(`WinError 5`) 이슈가 간헐적으로 발생.
- 이번 반영은 `py_compile` + 스모크 스크립트로 로딩/엄격모드 동작을 우선 검증.

## 다음 우선순위
1. ConclusionViewBuilder 키워드 매칭 정교화 (의미적 유사도 확장)
2. E2E 통합 테스트: 루프 3회 + ConclusionView 흐름 검증
3. override 프로필(`conservative/balanced/aggressive`) 전환을 API/운영 파라미터로 연결.
4. Linux cron 대응 스크립트/운영 가이드 추가

## 운영 실행 예시
```bash
python tools/revision_rule_apply_overrides.py --db data/memory.db --preset balanced
```
- 기본 출력 파일: `data/revision_rule_overrides.auto.json`
- `ChatPipeline`은 시작 시 해당 파일을 자동 로드한다.

## 운영 스케줄러(Windows Task Scheduler)
- 1회 실행:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\run_revision_rule_override_job.ps1 -ProjectRoot . -Preset balanced
```
- 스케줄 등록(매일 03:30):
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup_revision_rule_scheduler.ps1 -ProjectRoot . -TaskName "MACHI-MK5-RevisionRuleOverride" -DailyTime "03:30" -Preset balanced
```
- 스케줄 등록(30분 주기):
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup_revision_rule_scheduler.ps1 -ProjectRoot . -TaskName "MACHI-MK5-RevisionRuleOverride" -RepeatMinutes 30 -Preset balanced
```
