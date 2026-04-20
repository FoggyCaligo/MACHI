# MK5 Handoff

업데이트: 2026-04-20

## 이번 세션 핵심 변경 (2026-04-20)

### Think→Search 루프 구조화
- `chat_pipeline.py`의 1회 고정 흐름을 최대 3회 루프(`_THINK_SEARCH_MAX_LOOPS`)로 교체
- Python `for-else` 패턴: break(검색 결과 없음) 시 정상 종료, 완주 시 최종 Think 1회 추가
- 루프 내 Ollama 관련 타임아웃 3배 상향 (QUESTION_SLOT_PLANNER, SEARCH_SCOPE_GATE, SEARCH_COVERAGE_REFINER, OLLAMA_TIMEOUT, REQUEST_TIMEOUT)
- 루프 밖 단일 실행 컴포넌트(Verbalizer, ModelFeedback, ModelEdgeAssertion) 타임아웃은 유지

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
- `ModelFeedbackService`/`ModelEdgeAssertionService`/`ConnectTypePromotionService` 연계 구조를 계속 사용.
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

## 테스트/검증 메모
- Windows 환경에서 `pytest` temp/cache 디렉터리 권한(`WinError 5`) 이슈가 간헐적으로 발생.
- 이번 반영은 `py_compile` + 스모크 스크립트로 로딩/엄격모드 동작을 우선 검증.

## 다음 우선순위
1. override 프로필(`conservative/balanced/aggressive`) 전환을 API/운영 파라미터로 연결.
2. E2E 회귀에서 rule override가 실제 deactivation/merge 분기 결과를 바꾸는지 시나리오 추가 확대.
3. 필요 시 cron/스케줄러로 자동 생성 주기 운영화.

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
