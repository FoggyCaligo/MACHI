# Trust & Revision Rule

업데이트: 2026-04-16

## 목표
- 단발성 충돌로 구조를 즉시 바꾸지 않는다.
- 신뢰도(trust), 충돌압력(contradiction pressure), 근거 누적(evidence)을 함께 보고 revision을 실행한다.
- revision 판단과 실행은 모두 edge-first 구조에서 처리한다.

## 현재 실행 흐름
1. `ContradictionDetector`가 신호를 생성한다.
2. `TrustManager`가 base edge의 `trust_score`, `conflict_count`, `contradiction_pressure`를 갱신한다.
3. `RevisionEdgeService`가 marker edge를 누적한다.
   - `conflict_assertion`
   - `revision_pending`
   - `deactivate_candidate`
   - `merge_candidate`
4. `StructureRevisionService`가 `RevisionExecutionRule` 테이블로 실행 여부를 판정한다.
5. 결과를 graph event로 기록한다.
   - `edge_revision_pending`
   - `edge_deactivated_for_revision`
   - `edge_revision_merge_executed`

## 실행 정책
- 규칙 단위 분기: `edge_family + connect_type` 조합
- 게이트 단위:
  - trust/pressure/conflict_count
  - marker support count
  - marker evidence score
- override 정책:
  - 런타임에서 rule override JSON을 로드해 규칙을 덮어쓴다.
  - 설정: `REVISION_RULE_OVERRIDES_PATH`, `REVISION_RULE_PROFILE`, `REVISION_RULE_OVERRIDES_STRICT`

## 운영/튜닝
- 분석: `tools/revision_rule_report.py`
- 적용: `tools/revision_rule_apply_overrides.py`
- 스케줄: `tools/run_revision_rule_override_job.ps1`, `tools/setup_revision_rule_scheduler.ps1`

## 주의
- 과거 `revision_candidate_flag` 중심 실행은 제거되었다.
- 현재 실행 경로는 marker edge 기반으로 고정되어 있다.
