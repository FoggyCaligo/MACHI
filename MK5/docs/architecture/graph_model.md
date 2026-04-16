# Graph Model

업데이트: 2026-04-16

## 기본 원칙
- MK5는 문장 저장소가 아니라 “사실/관계 그래프”다.
- 사용자/어시스턴트/검색 입력은 같은 그래프에 들어가고, 신뢰도 정책만 다르게 적용된다.
- 사고는 전체 그래프가 아니라 `ThoughtView`(활성 부분 그래프)에서 수행한다.

## Node
- 핵심 필드:
  - `address_hash`
  - `node_kind`
  - `raw_value`
  - `normalized_value`
  - `trust_score`
  - `stability_score`
  - `payload`
  - `is_active`

## Edge
- 핵심 필드:
  - `source_node_id`
  - `target_node_id`
  - `edge_family` (`concept | relation`)
  - `connect_type` (`flow | neutral | opposite | conflict`)
  - `relation_detail` (kind, provenance, proposal, scope 등)
  - `edge_weight`
  - `support_count`
  - `conflict_count`
  - `contradiction_pressure`
  - `trust_score`
  - `is_active`

## Pointer
- partial reuse/참조 연결을 표현한다.
- 중복 노드 생성을 줄이고, merge/rewrite 단계에서 재배선 근거로 사용한다.

## Graph Event
- 그래프 상태 변화 로그다.
- 예시:
  - ingest
  - trust update
  - revision pending/deactivate/merge
  - node merge
  - intent snapshot 결정

## Revision 관점 요약
- 실행 기준은 edge marker 누적 + rule gate다.
- 규칙은 `StructureRevisionService`에서 관리되며 override로 덮어쓸 수 있다.
