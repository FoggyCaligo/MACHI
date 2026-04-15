# Thought flow

## 현재 사고 루프
### 1. 입력 ingest
`GraphIngestService`
- chat_message 저장
- graph_event 기록
- meaning block 분해
- node 재사용/생성
- edge / pointer 반영

### 2. activation
`ActivationEngine`
- 현재 입력 기준 seed block 생성
- seed node 탐색
- local node / edge / pointer 수집
- `ThoughtView` 생성
- `PatternDetector`로 활성 패턴 추가

### 3. thinking
`ThoughtEngine`
- `ContradictionDetector`
- `TrustManager`
- `StructureRevisionService`
- `IntentManager`
- `ConclusionBuilder`

순서상 의미:
- 먼저 구조 충돌을 본다
- 그다음 trust와 revision 후보를 반영한다
- 필요 시 shallow merge / deactivation을 수행한다
- 그 상태를 바탕으로 현재 intent snapshot을 고른다
- 마지막에 explanation 중심 conclusion을 만든다

### 4. search enrichment
`SearchSidecar`
- 필요한 경우 외부 검색을 시도한다
- 검색 결과도 같은 그래프에 낮은 trust로 반영된다
- 이후 activation / thinking을 한 번 더 수행할 수 있다

### 5. verbalization
- `DerivedActionLayer` 생성
- verbalizer가 최종 사용자 응답 생성
- assistant 응답도 다시 그래프에 반영된다

---

## IntentManager의 현재 의미
현재 intent manager는 완전한 “목표 생성기”가 아니다.
지금 사이클의 그래프 상태를 보고,
무엇을 우선하는 사고로 볼지 정하는 **snapshot manager**다.

현재 판단 근거:
- contradiction 수
- revision 수
- inquiry / relation block 수
- edge / pointer / pattern 수
- 최근 assistant turn의 intent snapshot과의 overlap

현재 산출값:
- `live_intent`
- `snapshot_intent`
- `previous_snapshot_intent`
- `shifted`
- `continuation`
- `shift_reason`
- `sufficiency_score`
- `stop_threshold`
- `should_stop`

---

## 아직 남은 것
- drive → live intent → snapshot intent로 이어지는 더 깊은 의도 함수
- 실패 히스토리에 따라 stop threshold가 더 장기적으로 조정되는 구조
- multi-cycle thought loop
