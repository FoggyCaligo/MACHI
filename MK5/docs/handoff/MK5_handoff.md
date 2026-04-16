# MK5 Handoff

업데이트: 2026-04-16

## 이번 세션 핵심 변경
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
