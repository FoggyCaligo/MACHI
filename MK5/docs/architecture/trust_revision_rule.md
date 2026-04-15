# Trust revision rule

## 현재 기본 원칙
MK5는 새 구조가 들어와도 기존 구조를 즉시 부수지 않는다.
기본은 구조 보존이고,
반복 충돌이 누적될 때만 trust를 낮추고 revision을 검토한다.

---

## 현재 trust 하락 트리거
`ContradictionDetector`가 감지한 signal이 들어오면 `TrustManager`가 아래 값을 누적한다.

- `trust_score` 하락
- `conflict_count` 증가
- `contradiction_pressure` 증가

그리고 아래 중 하나를 만족하면 revision candidate로 올린다.

- pressure >= `2.0`
- conflict_count >= `2`
- trust_score <= `0.42`

즉, 현재는 **조금 얕은 누적량**에서 revision review 대상으로 올라간다.

---

## revision review 단계
`StructureRevisionService`는 revision candidate를 검토한다.

현재 우선순위:
1. shallow duplicate merge 가능 여부 확인
2. merge가 아니면 deactivation 필요 여부 확인
3. 둘 다 아니면 pending 유지

---

## 현재 merge 정책
현재 merge는 **revision 단계에서만** 일어난다.

즉,
- ingest 직후 자동 merge는 하지 않는다.
- revision candidate review 중에만 merge를 시도한다.
- 기준은 duplicate-like node에 한정한다.

현재 merge 허용 조건:
- `node_kind` 동일
- 그리고 아래 중 하나
  - `address_hash` 동일
  - `normalized_value` 동일
  - alias set 교집합 존재

의미:
- trigger는 얕게
- merge 허용 범위는 보수적으로

---

## deactivation 기준
merge로 처리하지 못한 edge는 아래 기준으로 deactivate를 검토한다.

- trust_score <= `0.2`
- contradiction_pressure >= `4.0`
- conflict_count >= `4`

그 전까지는 revision pending으로 유지될 수 있다.

---

## 아직 안 된 것
- relation retyping
- merge 후보 설명성 강화
- merge / deactivate를 묶는 graph commit service
- 더 깊은 구조 재조직형 revision
