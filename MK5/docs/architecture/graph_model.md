# Graph Model

업데이트: 2026-04-16

## 기본 원칙
- MK5는 문장 저장소가 아니라 세계 그래프다.
- 사용자/어시스턴트/검색 입력은 같은 그래프에 들어가고, 신뢰도 정책만 다르게 시작한다.
- 사고는 전체 그래프가 아니라 `ThoughtView` 같은 **국부 활성화 그래프**에서 수행한다.
- 하지만 특정 Node/Edge는 **다이렉트 조회**로 접근 가능해야 한다.

즉 MK5는:
- 사고 경로 = local activation
- 조회/관리 경로 = direct access
로 나뉜다.

## Node
현재 방향은 과세분화된 node kind보다 **일반 node** 하나를 기본으로 두는 쪽이다.

핵심 필드:
- `address_hash`
- `raw_value`
- `normalized_value`
- `trust_score`
- `stability_score`
- `payload` 또는 `data/note`
- `is_active`
- `created_at`
- `updated_at`

원칙:
- Node의 의미를 미리 코드 타입표로 박아두지 않는다.
- 상위/하위 개념, 표상군, 관계성은 Node 자체보다 **Edge와 연결 구조**로 읽는다.

## Edge
핵심 필드:
- `source_node_id`
- `target_node_id`
- `edge_family` (`concept | relation`)
- `connect_type` (`flow | neutral | opposite | conflict`)
- `relation_detail` 또는 `data/note`
- `edge_weight`
- `support_count`
- `conflict_count`
- `contradiction_pressure`
- `trust_score`
- `is_active`
- 시간 필드들

원칙:
- 구조 의미의 본체는 `family + connect_type + 방향 + 상태값`이다.
- `relation_detail.kind`나 `connect_semantics` 같은 문자열 ontology는 본체가 아니다.
- `data/note`는 보조 설명, provenance, proposal 같은 잔여 정보 공간이다.

## Pointer
- partial reuse/참조 연결을 표현한다.
- 중복 노드 생성을 줄이고, merge/rewrite 단계의 재배선 근거가 된다.

## Graph Event / Log
- 그래프 상태 변화 로그다.
- 현재 상태를 직접 대체하지 않고, **bounded append-only history**로 유지한다.
- 노드/에지별 로그 수에는 상한이 있을 수 있으며, 한계를 넘으면 가장 오래된 기록부터 정리한다.

예시:
- ingest
- trust update
- conflict support/conflict 누적
- revision pending/deactivate/merge
- node merge
- intent snapshot 결정

## 기준시점 재형성
- `2026년 3월의 Machi` 같은 것은 새 Node를 만드는 문제가 아니다.
- 현재 Node/Edge와 이벤트 로그를 바탕으로, 필요할 때 과거 시점의 **국부 활성화 그래프**를 재형성하는 문제다.
- 기본 시드 방식은 특정 Node를 직접 seed로 잡는 쪽이 우선이다.

## Revision 관점 요약
- revision은 문자열 라벨보다 `connect_type + 상태값 + 누적 evidence` 중심으로 간다.
- conflict는 별도 `contradicts` semantics보다 `connect_type='conflict'`와 상태값으로 읽는 방향이 맞다.
