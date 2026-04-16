# Edge Family And Connect Type Design

업데이트: 2026-04-16

## 핵심 결론
MK5의 Edge는 더 이상 `edge_type`이나 `relation_detail.kind` 중심으로 읽지 않는다.
현재 기준의 본체는 아래 네 가지다.

- `edge_family`: `concept | relation`
- `connect_type`: `flow | neutral | opposite | conflict`
- `from -> to`
- 상태값: `support_count`, `conflict_count`, `contradiction_pressure`, `trust_score`

`relation_detail`은 구조 의미의 본체가 아니라 보조 메타데이터 층이다.
즉 그래프가 이미 구조로 말하고 있는 것을 문자열 라벨로 한 번 더 복제하지 않는다.

## connect_type의 의미
`connect_type`은 관계 종류보다 **연결의 방향성 / 방향 성질**에 가깝다.

- `flow`
  - 상위에서 하위로 이어지는 분화, 한쪽에서 다른 쪽으로 향하는 관계 흐름
- `neutral`
  - 표상/호칭/동류처럼 대칭성이 강한 연결
- `opposite`
  - 같은 축 안의 반대편 연결
- `conflict`
  - 충돌/반박/서로 양립하기 어려운 방향성

저장은 항상 `from -> to`로 이루어지지만, 탐색은 양방향 가능해야 한다.
따라서 `concept / flow / 사람 -> 재용`이 있으면:
- 사람에서 읽을 때: 재용은 사람의 하위 분화 개념
- 재용에서 읽을 때: 사람은 재용의 상위 개념 쪽
으로 읽을 수 있다.

## 새 connect_type의 추가
초기 기본 집합은 작게 유지한다.
하지만 모델은 새로운 연결 방향성이 반복적으로 필요하다고 판단할 수 있어야 한다.

현재 원칙:
- allowlist 밖 타입을 즉시 정식 채택하지 않는다.
- 우선 Edge/Node의 `data` 또는 로그에 제안 후보를 남긴다.
- 충분한 반복과 근거가 누적되면 이후 승격한다.

즉 connect type은 고정 표가 아니라, 그래프와 함께 성숙할 수 있는 구조다.

## relation_detail의 위치
`relation_detail`은 구조 의미를 대신하지 않는다.
현재는 아래와 같은 보조 정보만 남기는 방향이 맞다.

- provenance / source 보조 정보
- confidence / note
- proposal 관련 정보
- 사람이 읽기 위한 짧은 설명

삭제 또는 비중 축소 대상:
- `relation_detail.kind`
- `connect_semantics`
- `same_as`, `is_a`, `parent_of`, `child_of`, `related_to`, `contradicts` 같은 문자열 ontology

이런 정보는 가능한 한 그래프 구조 자체로 읽어야 한다.

## 같은 두 Node 사이의 복수 Edge
같은 두 Node 사이에도 복수 Edge는 공존 가능하다.

예:
- `concept / flow / 사람 -> 재용`
- `concept / neutral / 재용 -> Jay`
- `relation / flow / 재용 -> Machi`
- `relation / conflict / 재용 -> 어떤_반대_주장`

중복 여부는 단순 node pair가 아니라:
- family
- connect_type
- 방향
- 상태값
의 조합으로 읽어야 한다.

## 현재 우선과제
1. 코드/문서에서 `kind` 의존 제거
2. contradiction/revision을 `connect_type + 상태값` 중심으로 정렬
3. ingest에서 `flow / neutral / conflict`를 더 구조적으로 생성하는 경로 강화
