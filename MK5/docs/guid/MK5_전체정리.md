# MK5 전체정리 (마스터 문서)

업데이트: 2026-04-16

## 1. 현재 정체성
MK5는 “그래프 중심 인지 시스템”이다.  
LLM은 구조 판정/제안/언어화에 참여하는 하위 모듈이고, 장기 상태와 판단 근거의 중심은 그래프다.

## 2. 실행 파이프라인
1. User ingest
2. Activation (`ThoughtView`)
3. Thinking (contradiction → trust update → revision)
4. Search sidecar + 재사고
5. Conclusion + action layer
6. Verbalization
7. Assistant ingest

## 3. Edge-first 기준
- `edge_family`: `concept | relation`
- `connect_type`: `flow | neutral | opposite | conflict`
- `relation_detail`: 관계 세부 의미(kinds/provenance/proposal/scope)

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

## 5. 최근 완료 항목
- temporary edge 정리(topic shift 기반)
- model feedback commit 연계
- model edge assertion 연계
- connect type promotion 강화
- revision rule analytics/tuner/report 추가
- override 자동 적용 도구/스케줄러 추가

## 6. 운영 자동화
- 분석:
  - `tools/revision_rule_report.py`
- 적용:
  - `tools/revision_rule_apply_overrides.py`
- 주기 실행(Windows):
  - `tools/run_revision_rule_override_job.ps1`
  - `tools/setup_revision_rule_scheduler.ps1`

## 7. 현재 남은 우선과제
1. override 프로필 전환 A/B 운영 가이드
2. E2E 회귀 확대(다중 rule/family/connect_type)
3. Linux cron 운영 스크립트 추가

## 8. 문서 체계
- 마스터: `docs/guid/MK5_전체정리.md`
- 아키텍처 상세: `docs/architecture/*`
- 전략: `docs/guid/MK5_검색_및_검증_전략.md`
- 핸드오프: `docs/handoff/MK5_handoff.md`
- 단기 실행: `docs/todo/현재작업.txt`
