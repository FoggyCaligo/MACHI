# Graph model

## 기본 원칙
MK5의 세계 그래프는 문장 저장소가 아니라, 재사용 가능한 의미 단위를 누적하는 구조다.

- 원문 전체 = provenance
- 그래프 노드 = 의미블록 / 개념 단위
- 엣지 = 관계 / support / conflict / revision 압력
- 포인터 = partial reuse / 기존 노드 참조

---

## node
대표 필드:
- `address_hash`
- `node_kind`
- `raw_value`
- `normalized_value`
- `trust_score`
- `stability_score`
- `payload`
- `is_active`

의미:
- 같은 입력 전체를 그대로 저장하는 것이 아니라
- 재사용 가능한 단위가 node로 들어간다.

---

## edge
대표 필드:
- `source_node_id`
- `target_node_id`
- `edge_type`
- `edge_weight`
- `support_count`
- `conflict_count`
- `contradiction_pressure`
- `trust_score`
- `revision_candidate_flag`
- `is_active`

현재 엣지는 단순 연결선이 아니라,
**지지와 충돌의 누적량**을 함께 가진다.

---

## pointer
pointer는 partial reuse를 표현한다.
즉, 새 입력이 기존 노드 일부를 재사용할 때
중복 복사 대신 참조를 남긴다.

현재 역할:
- 부분 포함 관계 기록
- 추후 merge / rewrite 시 재배선 대상

---

## graph event
graph event는 그래프가 어떻게 바뀌었는지의 이력이다.

예:
- ingest root event
- trust update event
- edge revision pending
- edge deactivation
- intent snapshot decided
- node merged

즉, 세계 그래프 본체와는 별도로
**변화의 로그**를 남긴다.

---

## 현재 구조 재작성 수준
현재 가능한 재작성은 아래 수준이다.

1. trust 하락
2. revision candidate 표기
3. revision review
4. duplicate-like 노드 shallow merge
5. edge deactivation
6. pointer rewrite

아직 안 된 것:
- 공통부 추출 기반 상위 개념 재조직
- relation retyping 고도화
- graph commit orchestration
