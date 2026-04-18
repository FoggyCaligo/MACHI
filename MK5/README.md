# MACHI MK5

MK5는 **그래프 중심 인지 시스템**을 목표로 하는 실험 런타임입니다.
현재 기준 핵심 방향은 다음과 같습니다.

- 입력은 먼저 그래프에 적재되지만, **현재 입력 자체는 근거가 아니라 접근 키**로 취급한다.
- 질의 처리는 **질문 대상 grounding**을 우선으로 보고, 부족한 의미 단위는 검색으로 그래프를 채운다.
- 검색은 답변 사후 보강이 아니라, 가능하면 **think 이전의 graph completion 단계**로 재배선한다.
- 답변은 모델 일반지식보다 **그래프/검색 근거 우선**이어야 하며, 근거가 부족하면 모른다고 답한다.

## 현재 문서 진입점
- `docs/README.md` — 문서 인덱스
- `docs/runtime_philosophy_and_contract.md` — 현재 철학과 답변 계약
- `docs/runtime_change_summary.md` — 현재 런타임 변천 요약
- `SLIMMED_RUNTIME.md` — 현재 슬림 런타임 요약
- `docs/refactor/MK5_refactoring_design_draft.md` — 리팩토링 설계 초안
- `docs/refactor/MK5_current_vs_target_refactor_map.md` — 현재 구조 vs 목표 구조 대응표
- `docs/refactor/MK5_file_level_refactor_plan.md` — 파일 단위 변경 계획서

## 현재 상태 요약
현재 코드는 아직 과도기 상태다.

- concept-access, grounding 중심 방향은 반영되어 있다.
- 그러나 전체 핫패스는 아직 완전히 `search-before-think`로 재배선되지 않았다.
- assistant full answer ingest 제거, activation 1차 제거, 입력 의미 분해 LLM 도입 등은 리팩토링 작업 항목으로 남아 있다.

즉, 현재 코드는 **실행 가능한 중간 정리본**이고,
문서에 정의된 목표 구조로 단계적으로 수렴시키는 중이다.
