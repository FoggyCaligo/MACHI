# MK5 설계 초안: schema / Edge dataclass / repository 마이그레이션

기준 시점: 2026-04-16

## 1. 목적
이 문서는 문서로 합의한 `edge_family + connect_type + relation_detail` 구조를 현재 MK5 코드에 어떻게 점진적으로 반영할지 정리한다.

대상은 다음 세 가지다.

- `storage/schema.sql`
- `core/entities/edge.py`
- `storage/sqlite/edge_repository.py` 및 dedupe 기준

핵심 원칙은 "기존 구조를 한 번에 깨지 않고, 호환 가능한 1차 마이그레이션으로 옮긴다"이다.

## 2. 현재 구현 상태 요약

### schema.sql
현재 `edges` 테이블은 다음 구조를 가진다.

- `source_node_id`
- `target_node_id`
- `edge_type`
- `relation_detail_json`
- trust / support / conflict / revision 관련 필드
- `created_from_event_id`
- `last_supported_at`
- `last_conflicted_at`
- `created_at`
- `updated_at`

### Edge dataclass
현재 `Edge` 엔티티는 다음 핵심 필드를 가진다.

- `edge_type: str`
- `relation_detail: dict`

즉 지금도 세부 데이터를 `relation_detail`에 넣을 수는 있지만, 큰 구조값이 `edge_type` 하나에 과하게 몰려 있다.

### repository dedupe
현재 `SqliteEdgeRepository.find_active_relation()`은 아래 기준으로 dedupe를 한다.

- `source_node_id`
- `target_node_id`
- `edge_type`
- `is_active`

이 기준으로는 앞으로 필요한 다음 경우를 제대로 분리하기 어렵다.

- 같은 두 Node 사이의 `concept` Edge와 `relation` Edge 공존
- 같은 `edge_family` 안에서도 `flow` / `neutral` / `opposite` 공존
- 같은 family/type라도 세부 semantics가 다른 Edge 공존

## 3. 1차 마이그레이션 원칙
1차 마이그레이션은 다음 원칙으로 간다.

1. `edge_type`를 당장 삭제하지 않는다.
2. 대신 `edge_family`와 `connect_type`를 새 칼럼으로 추가한다.
3. 세부 의미는 계속 `relation_detail_json`에 둔다.
4. 기존 `edge_type`는 호환성 유지를 위해 잠시 남긴다.
5. 신규 코드부터는 `edge_family`와 `connect_type`를 우선 읽고, 과거 데이터는 필요 시 `edge_type`에서 해석한다.

즉 1차 목표는 "새 구조를 수용할 수 있는 형태"를 만드는 것이지, 기존 데이터 모델을 한 번에 완전히 갈아엎는 것이 아니다.

## 4. schema.sql 초안

### A. edges 테이블 변경 방향
추가 권장 칼럼:

- `edge_family TEXT NOT NULL DEFAULT 'relation'`
- `connect_type TEXT NOT NULL DEFAULT 'flow'`

선택적 추가 권장 칼럼:

- `last_updated_event_id INTEGER`
- `last_supported_event_id INTEGER`
- `last_conflicted_event_id INTEGER`

의도:

- `edge_family`
  - `concept`
  - `relation`
- `connect_type`
  - 초기 집합: `flow`, `neutral`, `opposite`

세부 의미는 계속 `relation_detail_json`에 둔다.

예:

```json
{
  "connect_semantics": "specialized_concept",
  "connect_semantics": "creator_relation",
  "confidence": 0.82,
  "proposed_connect_type": "reflective",
  "proposal_reason": "기존 flow/neutral/opposite로 설명 어려움"
}
```

### B. index 초안
기존 pair index는 다음처럼 바뀌는 것이 좋다.

현재:

- `(source_node_id, target_node_id, edge_type, is_active)`

권장:

- `(source_node_id, target_node_id, edge_family, connect_type, is_active)`

필요시 장기적으로는 relation detail 안의 핵심 semantics 일부를 정규화해서 더 구체적인 dedupe key를 둘 수 있지만, 1차에서는 family/type까지만 index에 올리는 편이 안전하다.

## 5. Edge dataclass 초안

### 현재
```python
class Edge:
    edge_type: str = "related_to"
    relation_detail: dict[str, Any]
```

### 권장 1차 형태
```python
class Edge:
    edge_family: str = "relation"
    connect_type: str = "flow"
    edge_type: str = "related_to"
    relation_detail: dict[str, Any]
```

설명:

- `edge_family`
  - 큰 축
- `connect_type`
  - 연결 성격
- `edge_type`
  - 과거 호환용 또는 migration bridge
- `relation_detail`
  - 세부 semantics / provenance / confidence / proposal

즉 1차에서는 `edge_type`를 완전히 없애지 않고, 브리지 필드로 남긴다.

### 장기 목표
장기적으로는 다음 둘 중 하나로 수렴할 수 있다.

1. `edge_type` 제거
2. `edge_type`를 내부 generated label 정도로 축소

하지만 그 판단은 ingestion / activation / thinking이 새 구조를 안정적으로 쓰게 된 뒤에 하는 게 맞다.

## 6. repository 조회/저장 기준 초안

### A. add()
새 Edge 추가 시:

- `edge_family`
- `connect_type`
- `relation_detail_json`

을 함께 저장한다.

기존 `edge_type`는 다음처럼 임시 운영 가능하다.

- `concept_flow`
- `concept_neutral`
- `concept_opposite`
- `relation_flow`
- `relation_neutral`
- `relation_opposite`

즉 호환성용 문자열을 내부적으로 만들 수 있다.

### B. find_active_relation()
현재의 `find_active_relation(source, target, edge_type)`는 한계가 크다.

권장 1차 변경 방향:

```python
find_active_relation(
    source_node_id: int,
    target_node_id: int,
    *,
    edge_family: str,
    connect_type: str,
)
```

이 함수는 최소한:

- `source_node_id`
- `target_node_id`
- `edge_family`
- `connect_type`
- `is_active`

를 기준으로 찾는다.

### C. 향후 finer dedupe
가까운 미래에는 family/type만으로도 부족할 수 있다.

예:

- `relation / flow / creator_relation`
- `relation / flow / interaction_toward_user`

둘 다 같은 source/target에 공존 가능해야 하기 때문이다.

그래서 장기적으로는 dedupe 기준에 `relation_detail` 안의 정규화된 semantics key를 포함해야 한다.

예:

- `relation_detail["connect_semantics"]`

다만 1차에서는 DB 칼럼 추가보다, repository 내부에서 relation_detail을 읽어 비교하는 수준으로 먼저 시작하는 것이 무난하다.

## 7. 권장 dedupe 규칙
현재 합의를 반영한 권장 dedupe 규칙은 다음과 같다.

### 1차
동일 Edge로 간주:

- same `source_node_id`
- same `target_node_id`
- same `edge_family`
- same `connect_type`
- same normalized `connect_semantics` if present
- active only

### 공존 허용
다음은 공존 가능:

- 같은 source/target + 다른 `edge_family`
- 같은 source/target + 같은 family + 다른 `connect_type`
- 같은 source/target + 같은 family/type + 다른 semantics

예:

- `재용 -> Machi` with `concept / flow / specialized_concept`
- `재용 -> Machi` with `relation / flow / creator_relation`
- `재용 -> Machi` with `relation / neutral / interaction_cluster`

모두 동시에 존재 가능해야 한다.

## 8. migration 단계 제안

### 단계 1
- schema에 `edge_family`, `connect_type` 추가
- `Edge` dataclass에 같은 필드 추가
- repository row mapping 업데이트

### 단계 2
- 신규 코드에서 edge 생성 시 `edge_family`, `connect_type`를 명시
- 기존 `edge_type`는 호환용으로 병행

### 단계 3
- `find_active_relation()` 류 API를 family/type 기준으로 바꿈
- 기존 `edge_type` 기반 호출부를 점진적으로 교체

### 단계 4
- relation detail 안의 semantics key를 dedupe에 포함
- 필요하면 정규화 칼럼 추가 검토

## 9. 한 줄 요약
1차 마이그레이션의 목표는 `edge_type`를 즉시 없애는 것이 아니라, `edge_family`와 `connect_type`를 추가해 Machi가 개념/관계와 flow/neutral/opposite 구조를 안정적으로 저장하고, 같은 두 Node 사이의 복수 Edge 공존까지 허용하는 기반을 만드는 것이다.
