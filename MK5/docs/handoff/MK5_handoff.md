# MK5 Handoff

업데이트: 2026-04-16

## 이번 세션 핵심 변경
- `revision_candidate_flag` 기반 잔재 제거(패턴 레이어 포함)
- revision 실행을 marker edge 중심으로 정리
- `StructureRevisionService`에 `RevisionExecutionRule` 테이블 도입
  - family/connect_type별 deactivation/merge 임계치 분기 가능
- `SqliteEdgeRepository`의 업데이트 계열에서 `updated_at` 갱신 보강
  - `update_relation_detail`, `update_connect_type`, `deactivate`

## 임시 Edge 정책 반영
- identity anchor 링크 edge를 `session_temporary`로 저장
  - `relation_detail.temporary_edge=true`
  - `relation_detail.scope=session_temporary`
- topic 전환 시 정리 조건
  - `topic_continuity=shifted_topic`
  - `topic_overlap_count=0`
  - 위 조건이면 session temporary edge를 자동 deactivate
- 구현 위치
  - `core/update/temporary_edge_service.py`
  - `core/update/graph_ingest_service.py`
  - `app/chat_pipeline.py`

## 대명사 정책
- `나/너/그사람`은 문자열 휴리스틱으로 고정 해석하지 않음
- 기본 해석은 모델/사고 파이프라인에 맡김
- 그래프는 필요한 경우에만 임시 문맥 바인딩 edge를 사용

## 현재 남은 우선 작업
1. `RevisionExecutionRule` 고도화(세부 임계치/가중치)
2. concept/relation + connect_type 조합별 충돌 정책 정교화
3. E2E 회귀 테스트 확대(충돌/수정/승격/temporary cleanup)

## 주의 사항
- 기존 `memory.db` 재사용 대신 새 DB로 시작하는 정책과 현재 구조가 잘 맞음
- Windows에서 pytest temp/cache 권한 이슈(`WinError 5`)가 간헐적으로 발생

