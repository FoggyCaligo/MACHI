# Runtime Change Summary

## 2차 정리
- LLM-heavy search gate/slot/coverage 레이어 제거
- search need는 concept grounding 기준으로 단순화
- search query는 normalized concept 개별 발행만 사용
- 현재 입력에서 이번 턴에 생성된 노드는 grounding 근거에서 제외

## 물리적으로 제거된 파일
- `core/search/question_slot_planner.py`
- `core/search/search_scope_gate.py`
- `core/search/search_coverage_refiner.py`
- 관련 search/system prompt 파일들

## 현재 search 루프
1. 현재 입력에서 noun_phrase 기반 normalized concept 추출
2. concept별 prior grounding 검사
3. grounding 없는 concept만 개별 검색
4. search ingest
5. local activation / contradiction / trust / revision / conclusion
