# MK5 다음작업 로드맵

## A. 지금 바로 해야 하는 것

### A1. slot 기반 search 안정화
목표:
- 새 entity 누락 방지
- 새 aspect 누락 방지
- planner 실패 시 fail-open
- missing slot만 국소 search

완료 조건:
- `판금갑옷 + 찰갑 + 사슬갑옷 + 미늘갑옷 + 가죽갑옷`
  같은 질문에서 search false로 떨어지지 않음
- debug에 requested/covered/missing slot이 명확히 보임

### A2. hallucination 억제 강화
목표:
- grounded term이 없는 항목은 단정 금지
- missing aspect가 있으면 그 aspect도 단정 금지

완료 조건:
- 일부 항목만 search로 확인됐을 때,
  나머지를 자연스럽게 메워서 설명하지 않음

### A3. search failure visibility 고정
목표:
- provider failure와 no-result 분리
- transport failure를 실제 오류처럼 노출

완료 조건:
- 인터넷 끊김 / 404 / timeout에서 `error: search_transport_failure`
- debug에 `provider_errors`가 남음

---

## B. 그 다음에 해야 하는 것

### B1. trusted_search backend 확장
현재:
- 위키피디아 중심

다음:
- 다중 provider
- source_provenance / trust_hint 표준화
- dedup 전략 강화

### B2. conflict double-check
목표:
- 기존 그래프와 충돌 시, 검색 가능한 대상이면 external corroboration 수행
- corroboration 되면 trust 상승
- threshold 넘으면 graph update / revision 반영

### B3. post-search synthesis 강화
목표:
- 검색 결과를 단순 나열이 아니라 비교 축으로 재구성
- 예: 구조 / 방어력 / 기동성 / 장단점

---

## C. 코어 빈칸 채우기

### C1. `graph_commit_service.py`
필요성:
- merge / deactivate / rewrite / trust update를
  한 사이클의 구조 변경으로 안정적으로 묶을 orchestration이 필요함

### C2. `edge_update_service.py`
필요성:
- relation refinement / retyping / support accumulation 고도화 필요

### C3. `meaning_preserver.py` 또는 동등 계층
필요성:
- conclusion과 최종 사용자 응답 사이 의미 왜곡 감시

---

## D. 삭제 또는 보류 판단이 필요한 것
- `tools/response_runner.py`
- `app/orchestrator.py`
- `app/routes/chat.py`
- `core/verbalization/llm_verbalizer.py`

이 파일들은 지금 당장 다 구현해야 한다기보다,
**정말 쓸 구조인지 먼저 결정**하는 게 맞다.

---

## E. 다음 채팅에서 바로 할 수 있는 작업 순서
1. slot coverage / missing aspect 계산 보강
2. hallucination 억제 강화
3. trusted_search backend 확장
4. conflict double-check 정책 연결
5. graph_commit_service 설계 초안
