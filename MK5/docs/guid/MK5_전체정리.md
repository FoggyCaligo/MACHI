# MK5 전체정리 (마스터 문서)

업데이트: 2026-04-16

## 1) 현재 구조 요약
- MK5는 `graph-first cognition` 구조다.
- 사용자/검색/어시스턴트 입력을 동일 그래프에 적재하고, 사고는 `ThoughtView` 위에서 수행한다.
- LLM은 주로 판정/제안/언어화에 참여하며, 세계 상태의 기준은 그래프다.

## 2) Edge-first 모델
- 핵심 축
  - `edge_family`: `concept | relation`
  - `connect_type`: `flow | neutral | opposite | conflict`
  - `relation_detail`: 의미 상세(kind, provenance, proposal, scope 등)
- 과거 `revision_candidate_flag` 중심 흐름은 제거되고, revision marker edge 중심으로 전환됨.

## 3) 충돌/수정 파이프라인
1. `ContradictionDetector`가 시그널 감지
2. `TrustManager`가 base edge의 trust/pressure/conflict_count 갱신
3. `RevisionEdgeService`가 marker edge(`conflict_assertion`, `revision_pending`, `deactivate_candidate`, `merge_candidate`) 누적
4. `StructureRevisionService`가 규칙 테이블(`RevisionExecutionRule`)로 실행
5. 결과(`revision_pending`, `edge_deactivated`, `node_merged`)를 graph event로 기록

## 4) connect_type 제안/승격
- 모델이 허용 집합 밖 connect_type을 내면 즉시 확장하지 않고 `proposed_connect_type`으로 저장
- `ConnectTypePromotionService`가 반복성 + 신뢰도 + 출처 가중치로 승격 판단

## 5) 임시 Edge 정책 (신규)
- identity anchor에서 파생되는 문맥 연결 edge는 `session_temporary`로 저장
- `relation_detail`에 `temporary_edge=true`, `scope=session_temporary`를 기록
- `topic_continuity=shifted_topic` && `topic_overlap_count=0`이면 자동 deactivate

중요 원칙:
- `나/너/그사람` 같은 인칭대명사 해석은 문자열 휴리스틱으로 강제하지 않음
- 기본 해석은 모델/사고 파이프라인에 맡기고, 그래프는 “현재 문맥 바인딩”이 필요할 때만 임시 edge로 관리

## 6) 현재 남은 급한 작업
1. `RevisionExecutionRule` 테이블 고도화(가중치/임계치 세분화)
2. concept/relation + connect_type 조합별 충돌 정책 강화
3. E2E 회귀 테스트 확대(충돌 누적/비활성화/병합/승격/임시 edge 정리)

