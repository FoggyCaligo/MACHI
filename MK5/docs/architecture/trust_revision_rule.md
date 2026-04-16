# Trust & Revision Rule

업데이트: 2026-04-16

## 목표
- 단발성 충돌로 구조를 즉시 바꾸지 않는다.
- 신뢰도(trust), 충돌압력(contradiction pressure), support/conflict 누적을 함께 보고 revision을 실행한다.
- revision 판단과 실행은 edge-first 구조에서 처리한다.

## 현재 방향
1. `ContradictionDetector`가 구조와 상태값을 바탕으로 신호를 생성한다.
2. `TrustManager`가 base edge의 `trust_score`, `support_count`, `conflict_count`, `contradiction_pressure`를 갱신한다.
3. 필요한 경우 conflict edge 또는 revision-purpose marker edge를 생성/강화한다.
4. `StructureRevisionService`가 누적 상태와 규칙을 바탕으로 실행 여부를 판정한다.
5. 결과를 graph event/log로 기록한다.

## 핵심 원칙
- `relation_detail.kind` 같은 문자열 라벨에 revision을 의존시키지 않는다.
- `contradicts` 같은 별도 semantics보다 `connect_type='conflict'`와 상태값을 우선 사용한다.
- 어느 쪽을 더 믿을지는 개별 edge의 support/conflict/trust 누적으로 읽는다.

## 실행 정책
- 분기 기준은 우선 `edge_family + connect_type + 상태값`이다.
- 게이트 단위 예시:
  - trust
  - contradiction pressure
  - support/conflict count
  - marker edge 누적량
- override 정책은 필요하면 유지할 수 있지만, 그것이 현재 상위 설계 철학을 덮어쓰면 안 된다.

## 운영/튜닝
- 분석/리포트 도구는 유지 가능하다.
- 다만 규칙 튜닝은 `kind` 중심이 아니라 실제 그래프 구조와 상태값 중심으로 재정렬해야 한다.

## 주의
- 과거 `revision_candidate_flag` 중심 실행은 이미 제거되었다.
- 앞으로도 revision은 문자열 ontology보다 그래프 상태를 우선으로 해석해야 한다.
