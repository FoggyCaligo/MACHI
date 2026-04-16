# Revision Rule Scheduler (Windows)

업데이트: 2026-04-16

## 목적
- `tools/revision_rule_apply_overrides.py`를 주기 실행해
  `data/revision_rule_overrides.auto.json`을 자동 갱신한다.
- `ChatPipeline`은 다음 시작 시 자동으로 override 파일을 로드한다.

## 1회 수동 실행
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\run_revision_rule_override_job.ps1 -ProjectRoot . -Preset balanced
```

## 스케줄 등록

### 매일 03:30
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup_revision_rule_scheduler.ps1 -ProjectRoot . -TaskName "MACHI-MK5-RevisionRuleOverride" -DailyTime "03:30" -Preset balanced
```

### 30분 주기
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup_revision_rule_scheduler.ps1 -ProjectRoot . -TaskName "MACHI-MK5-RevisionRuleOverride" -RepeatMinutes 30 -Preset balanced
```

## 점검
- 즉시 실행:
```powershell
schtasks /Run /TN "MACHI-MK5-RevisionRuleOverride"
```
- 로그 파일:
  - `logs/revision_rule_apply.log`

## 삭제
```powershell
schtasks /Delete /TN "MACHI-MK5-RevisionRuleOverride" /F
```
