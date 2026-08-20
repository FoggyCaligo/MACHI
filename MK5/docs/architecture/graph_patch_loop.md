# MK5 GraphPatch Reasoning Loop 설계

작성: 2026-05-18
상태: 5단계 구현 기준 문서

## 배경

MK5의 다음 목표는 입력 그래프를 목적 그래프에 맞게 반복적으로 수정하다가, 더 이상 유의미한 변화가 줄어드는 시점에 결론 그래프로 확정하는 것이다.

이를 위해 그래프 수정의 최소 단위를 `GraphPatch`로 표준화하고, 5단계부터는 이 patch log를 수렴 판단에 사용한다.

## 핵심 결정

GraphPatch는 문자열 설명이 아니라 구조적 변경 단위다.

```text
GraphPatch
  op
  target_kind
  target_id
  source_hash
  target_hash
  before
  after
  reason
  loop_index
```

의미:

```text
op           add / update / remove / merge / fill_slot
kind         node / edge / slot / pair
source/target graph endpoint
before/after 변경 전후 상태 일부
reason       변경 발생 경로
loop_index   사고 루프 회차
```

## 4단계 구현

```text
GraphPatch dataclass 추가
TempThoughtGraph 내부 patch log 추가
add_node/add_edge/update_edge/remove_edge/merge_nodes/fill_slot에서 patch 기록
current_patches(), all_patches(), reset_delta() 연동
```

## 5단계 구현

5단계에서는 patch log를 기존 수렴 판단에 연결한다.

```text
previous_loop_patches
current_loop_patches
→ patch_overlap_ratio(previous, current)
→ overlap >= 0.5 이면 수렴 후보
```

구현 위치:

```text
MK5/core/thinking/graph_patch.py
  - patch_overlap_ratio(previous, current)

MK5/core/thinking/thought_engine.py
  - PATCH_CONVERGENCE_OVERLAP_RATIO = 0.5
  - _has_converged(..., previous_patches)
  - Think loop에서 prev_loop_patches 갱신
```

이 수렴 조건은 기존 조건을 대체하지 않는다. 기존 조건은 유지된다.

```text
delta.is_empty()
OR node/edge count no-change
OR patch overlap >= 0.5
```

## 중요한 제약

1. patch op는 실행 흐름의 구조 기록이다.
2. op 이름을 응답 타입이나 의미 ontology로 확장하지 않는다.
3. 사용자/AI identity, profile, topic, provenance 정책은 그대로 유지한다.
4. patch log는 WorldGraph 저장 본체가 아니라 현재 사고 턴의 추적 자료다.
5. patch overlap은 문자열 비교가 아니라 GraphPatch.structural_key 기준으로 계산한다.

## 아직 하지 않는 것

```text
GraphPatch planner
goal alignment scoring
patch 기반 ConclusionGraph 생성
unresolved_high_priority_slots 기반 수렴 조건
```

## 다음 단계

6단계에서는 ConclusionGraph relation 품질을 강화한다. 이후 단계에서 goal alignment score와 unresolved slot 기반 수렴 조건을 추가한다.

