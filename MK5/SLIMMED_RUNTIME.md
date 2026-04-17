# Slimmed Runtime

현재 런타임은 concept-access 중심의 최소 루프로 정리되어 있습니다.

- 현재 입력은 grounding 근거가 아니라 접근 키로만 사용
- normalized concept 전체는 그래프에 들어갈 수 있음
- search obligation/query emission은 핵심 concept 중심으로 제한
- 개념 결합 검색은 사용하지 않음
- 제거된 레이어: question_slot_planner, search_scope_gate, search_coverage_refiner
