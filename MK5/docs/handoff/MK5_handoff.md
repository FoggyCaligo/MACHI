# MK5 Handoff

업데이트: 2026-04-16

## 1) 이번 세션 핵심 변경
- edge-first 전환 후 잔재 제거 작업 진행
  - `SubgraphPattern.revision_candidate_flag` 제거
  - pattern repository의 `set_revision_candidate`, `list_revision_candidates` 제거
  - schema의 `subgraph_patterns.revision_candidate_flag` 제거
- revision은 marker edge 기반으로 동작
  - `RevisionEdgeService`가 `conflict_assertion / revision_pending / deactivate_candidate / merge_candidate`를 edge로 기록
  - `StructureRevisionService`가 marker 누적과 trust/pressure 조건으로 실행
- connect_type 승격 경로 유지
  - `ModelEdgeAssertionService` 제안
  - `ConnectTypePromotionService` 승격 (가중 evidence score)

## 2) 이번 세션 보강 포인트
- `SqliteEdgeRepository`에서 아래 업데이트 시 `updated_at`도 함께 갱신하도록 보강
  - `update_relation_detail`
  - `update_connect_type`
  - `deactivate`

## 3) 충돌 처리 상태 (현재)
- 충돌 감지: `ContradictionDetector`
- 신뢰도/압력 갱신: `TrustManager.bump_conflict`
- marker 기록: `RevisionEdgeService.record_conflict_assertion`
- 구조 수정: `StructureRevisionService.review_candidates`
  - 결과: `revision_pending` 또는 `edge_deactivated` 또는 `node_merged`

즉, conflict 감지 후 그래프 일부 비활성화/병합까지 이어지는 실행 경로는 활성 상태.

## 4) 주의 사항
- 기존 `memory.db`를 재사용하지 않고 새로 시작하는 정책이면 현재 구조와 더 잘 맞음
- Windows에서 pytest temp/cache 권한 이슈가 있어 회귀 검증이 간헐적으로 흔들릴 수 있음

## 5) 다음 작업 권장 순서
1. revision marker 실행 규칙을 deterministic table로 고도화
2. concept/relation + connect_type별 충돌 정책 분기 강화
3. 충돌→비활성화/병합 E2E 테스트를 더 촘촘히 확장

