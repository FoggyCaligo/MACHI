# MK5 overview

## 한 문장 요약
MK5는 입력을 의미블록으로 분해해 하나의 세계 그래프에 누적하고, 그 그래프의 국부 활성화 위에서 사고를 전개한 뒤 마지막에만 언어화하는 인지형 대화 시스템이다.

---

## MK4와의 차이
MK4의 중심은 revisable memory substrate 였다.
MK5의 중심은 **세계 그래프 기반 판단**이다.

즉,
- MK4 = evidence / memory / correction 중심
- MK5 = graph / activation / intent / conclusion 중심

둘은 단절이라기보다, 저장층에서 판단층으로 무게중심이 올라간 관계다.

---

## 핵심 구성요소
### 1. ingest
- 입력을 바로 답변하지 않는다.
- `InputSegmenter`가 의미블록을 만든다.
- `GraphIngestService`가 node / edge / pointer / event를 기록한다.

### 2. world graph
- user / assistant / search / file가 같은 그래프 안에 들어간다.
- 다만 `source_type × claim_domain`에 따라 trust가 다르다.

### 3. thought view
- 전체 그래프 전체를 사고에 쓰지 않는다.
- 현재 입력과 연결된 국부 부분만 `ThoughtView`로 활성화한다.

### 4. thinking
- contradiction 감지
- trust 하락
- revision review
- 필요 시 shallow merge 또는 edge deactivation
- intent snapshot 결정

### 5. conclusion
- 본체는 설명형 `CoreConclusion`
- `activated_concepts` / `key_relations`는 참조 목록
- 행동형은 `DerivedActionLayer`로 얇게 파생

### 6. verbalization
- conclusion을 한국어 응답으로 바꾸는 단계
- 언어화는 사고가 아니다

---

## 현재 구현 수준
현재 MK5는 “완성된 인지 엔진”은 아니다.
하지만 최소한 아래 루프는 닫혀 있다.

- user ingest
- activation
- thinking
- search enrichment
- re-thinking
- conclusion
- action layer
- verbalization
- assistant ingest

즉, **세계 그래프에 들어온 정보가 다시 다음 사고의 재료가 되는 최소 루프**는 이미 연결되어 있다.

---

## 현재 가장 중요한 미완료
- trusted_search 기반 검색 레이어
- `tools/ollama_client.py` 실구현
- `graph_commit_service.py`
- `edge_update_service.py`
- 더 깊은 개념 재구성형 merge
