# MK5 전체정리 (마스터 문서)

업데이트: 2026-04-16

## 1) 현재 아키텍처 요약
- MK5는 `graph-first cognition`을 지향한다.
- 입력(사용자/검색/어시스턴트)은 모두 그래프에 적재되고, 사고는 `ThoughtView` 기반으로 수행된다.
- LLM은 주로 언어화/판정/제안 모듈로 쓰이며, 세계 상태의 1차 저장소는 그래프다.

## 2) Edge 모델 (edge-first)
- Edge 핵심 축
  - `edge_family`: `concept` | `relation`
  - `connect_type`: `flow` | `neutral` | `opposite` | `conflict`
  - `relation_detail`: 의미 상세(`kind`, provenance, proposal 등)
- 충돌/수정 압력은 별도 플래그가 아니라 edge 기반으로 누적/판정한다.

## 3) 충돌 처리와 구조 수정 파이프라인
1. `ContradictionDetector`가 충돌 시그널을 감지
2. `TrustManager`가 base edge의 `conflict_count / contradiction_pressure / trust_score`를 갱신
3. 동시에 `RevisionEdgeService`가 revision-purpose marker edge(`kind=conflict_assertion` 등)를 기록/누적
4. `StructureRevisionService`가 marker 요약 + 임계치로 `revision_pending / edge_deactivated / node_merged` 실행
5. 실행 결과는 `graph_events`로 남음

핵심: `revision_candidate_flag` 중심 로직은 제거되고, marker edge 중심 실행기로 전환됨.

## 4) 모델 제안 connect_type 승격
- `ModelEdgeAssertionService`: 모델이 edge 제안을 생성 (허용 집합 밖 connect_type은 즉시 반영하지 않고 `proposed_connect_type`으로 저장)
- `ConnectTypePromotionService`: 반복/신뢰/출처 가중치 기반 evidence score로 승격
- 승격 시 `connect_type_promoted` 이벤트 기록

## 5) 검색/응답 경로
- 검색 필요 판단: 슬롯 기반(`entity` 우선), 결과에서 `aspect`를 회수하는 방향
- 검색 결과는 그래프에 재적재 후 재사고
- 모델 미선택 등 사용자 액션 가능한 오류는 `UserFacingChatError`로 명시 반환

## 6) 현재 강점
- Edge-first 정렬로 정책 일관성 증가
- 충돌/수정 이력이 marker edge로 남아 추적 가능
- connect_type 확장 제안과 승격 경로가 분리되어 안전함

## 7) 현재 남은 핵심 과제
- revision marker 규칙의 deterministic table 고도화
- concept/relation별 충돌 정책을 더 세밀하게 분기
- identity/topic continuity를 그래프 추론에서 더 직접 사용하도록 강화
- Windows 테스트 환경 권한 이슈(임시 경로) 안정화

