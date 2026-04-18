# Runtime Change Summary

업데이트: **Step B / meaning-analysis + usable grounding** 반영 버전

## 이번 변경의 핵심
이 버전은 기존의
- 입력 ingest → activation 1차 → thinking 1차 → search → search ingest → activation 2차 → thinking 2차
구조를 정리하고,

아래 방향으로 옮기는 중간 단계다.
- 입력 ingest
- 정규식 기반 candidate 분해
- **LLM 의미 라벨링(핵심도 / 검색정책 / 업데이트 필요성)**
- direct access
- usable하지 않은 개념 자동 search
- search ingest
- activation 1회
- thinking 1회
- verbalization
- assistant snapshot만 저장

## 이번 버전에서 실제로 바뀐 점

### 1. search-before-think
- 파일: `app/chat_pipeline.py`
- 변경:
  - search를 think 이전으로 이동
  - think는 1회만 수행
  - activation도 search 이후 1회만 수행
- 효과:
  - search 결과가 같은 턴의 사고/답변에 바로 반영됨
  - pre-search conclusion / post-search conclusion의 이중 구조를 제거

### 2. 입력 분해는 정규식 기반 후보 + LLM 후처리
- 파일: `app/chat_pipeline.py`
- 변경:
  - `GraphIngestService`가 만든 `blocks`를 재사용
  - 후보 noun phrase를 LLM이 읽고 다음 라벨을 붙임:
    - `importance`: primary / secondary / background / ignore
    - `search_policy`: search_if_unusable / local_only / ignore
    - `freshness_kind`: timeless / current_state / self_or_local / unknown
- 효과:
  - 새 노드를 대량 생성하지 않고,
  - 기존 후보들 중 무엇이 이번 질문의 핵심인지 좁혀서 본다.

### 3. direct access 성공 조건을 usable grounding으로 변경
- 파일: `core/search/search_need_evaluator.py`
- 변경:
  - `node exists`가 아니라 `node is usable for this question` 기준으로 판정
  - 상태:
    - `node_missing`
    - `mention_only`
    - `grounded_but_stale`
    - `grounded_and_usable`
    - `local_only`
- 효과:
  - 사용자 발화 때문에 막 생긴 빈 노드가 access 성공으로 오인되지 않음

### 4. mention-only 정책(안 1)
- 현재 입력으로 만들어진 노드는 허용되지만,
- **grounding 근거로 치지 않음**
- `created_from_event_id == current_root_event_id`인 노드는 `mention_only`로 간주
- effect:
  - direct access는 되더라도 search를 막지 못함

### 5. 개별 concept query만 발행
- 파일: `core/search/search_query_planner.py`
- 변경:
  - usable하지 않은 핵심 meaning unit마다 **개별 query** 발행
  - concept 결합 query 제거
- 효과:
  - query 폭발과 조합 기반 잡음을 줄임

### 6. activation 재-segmentation 제거
- 파일: `core/activation/activation_engine.py`
- 변경:
  - `ActivationRequest.seed_blocks`를 받으면 재분해 없이 그대로 사용
- 효과:
  - ingest에서 만든 block과 activation block이 어긋나지 않음

### 7. assistant full answer ingest 제거
- 파일: `app/chat_pipeline.py`
- 변경:
  - assistant 응답을 그래프에 다시 ingest하지 않음
  - 대신 `chat_messages`에 lightweight snapshot만 저장
- 효과:
  - assistant free-form 답변이 다시 그래프 근거처럼 오염되는 경로를 줄임

## 현재 정책 요약
- 현재 입력은 **접근 키**이지 grounding 근거가 아님
- LLM은 새 노드를 대량 생성하지 않고,
  **기존 candidate에 역할 라벨을 붙이는 용도**로만 사용
- search는 think 전에 끝나야 함
- direct access 실패 조건은 node 부재만이 아니라
  **usable grounding 부족** 전체임
- assistant full answer는 그래프 확장 경로에서 제거
