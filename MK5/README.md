# MK5

업데이트: 2026-04-16

## 프로젝트 성격
MK5는 그래프 기반 인지 파이프라인이다.  
입력을 그래프에 적재하고(`ingest`), 활성 그래프에서 사고/판정을 수행한 뒤(`thinking`), 최종 결론만 언어화한다(`verbalization`).

## 현재 핵심 구조
- Graph Ingest: `core/update/graph_ingest_service.py`
- Activation: `core/activation/activation_engine.py`
- Thinking: `core/thinking/thought_engine.py`
  - contradiction/trust/revision(rule 기반)
- Search Sidecar: `core/search/*`
- Verbalization: `core/verbalization/*`
- Orchestration: `app/chat_pipeline.py`

## Edge-first 정책
- edge 의미 축:
  - `edge_family`: `concept | relation`
  - `connect_type`: `flow | neutral | opposite | conflict`
  - `relation_detail`: kind/provenance/proposal/scope 등 상세 의미
- revision 실행:
  - marker edge 누적 + `RevisionExecutionRule` 게이트
- runtime override:
  - `REVISION_RULE_OVERRIDES_PATH`
  - `REVISION_RULE_PROFILE`
  - `REVISION_RULE_OVERRIDES_STRICT`

## 자동 튜닝/적용
- 분석: `python tools/revision_rule_report.py --db data/memory.db --suggest`
- 적용: `python tools/revision_rule_apply_overrides.py --db data/memory.db --preset balanced`
- 기본 override 파일: `data/revision_rule_overrides.auto.json`

## Windows 실행
```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

## 운영 스케줄(Windows)
- 1회 실행:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\run_revision_rule_override_job.ps1 -ProjectRoot . -Preset balanced
```
- 스케줄 등록:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup_revision_rule_scheduler.ps1 -ProjectRoot . -TaskName "MACHI-MK5-RevisionRuleOverride" -DailyTime "03:30" -Preset balanced
```

## 참고 문서
- 마스터: `docs/guid/MK5_전체정리.md`
- 아키텍처: `docs/architecture/*`
- 핸드오프: `docs/handoff/MK5_handoff.md`
- 현재작업: `docs/todo/현재작업.txt`
