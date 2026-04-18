# MK5 Docs Index

업데이트: 2026-04-18

## 가장 먼저 볼 문서
- `runtime_philosophy_and_contract.md`
- `runtime_change_summary.md`
- `../SLIMMED_RUNTIME.md`

## 리팩토링 기준 문서
- `refactor/MK5_refactoring_design_draft.md`
- `refactor/MK5_current_vs_target_refactor_map.md`
- `refactor/MK5_file_level_refactor_plan.md`

## 현재 런타임 관련 문서
- `architecture/MK5_overview.md`
- `architecture/thought_flow.md`
- `architecture/graph_model.md`
- `architecture/trust_revision_rule.md`
- `architecture/edge_family_connect_type_design.md`
- `runtime_philosophy_and_contract.md`
- `runtime_change_summary.md`
- `../SLIMMED_RUNTIME.md`

## 현재 합의된 핵심 원칙
1. 현재 입력은 그래프 접근 키이지, 자동으로 근거가 아니다.
2. 질문 대상 grounding이 없으면 검색으로 그래프를 채운다.
3. think는 가능하면 search 이후 한 번만 돈다.
4. 답변은 evidence-first이며, 근거가 부족하면 모른다고 답한다.
5. assistant full answer를 다시 그래프 근거로 넣는 경로는 제거 대상이다.

## 현재 문서 정합성 주의
오래된 문서 중 일부는 아직 과거 런타임의 흔적을 포함할 수 있다.
현재 구현/설계 판단은 아래 문서를 우선 기준으로 삼는다.

- `runtime_philosophy_and_contract.md`
- `refactor/MK5_refactoring_design_draft.md`
- `refactor/MK5_file_level_refactor_plan.md`
