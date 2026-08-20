# MK5 AnswerContract 정책

작성: 2026-05-18  
상태: 구현 반영 초안

## 1. 문제

기존 GraphToLang은 ConclusionView의 많은 내부 상태를 거의 그대로 LLM에 넘겼다.

```text
핵심 키워드
참고 개념
현재 사용자 맥락
ProfileRecallView
ClaimConflict
결론 그래프
근거 연결
지식 및 검색 결과
```

대화가 길어질수록 `[근거 연결]`이 수십~수백 줄로 커지고, LLM은 그래프 사고 결과를 언어화하는 대신 raw graph dump를 다시 해석하게 된다.

## 2. 핵심 결정

AnswerContract는 LLM으로 만들지 않는다.

```text
ConclusionView
  → Python AnswerContractBuilder
  → AnswerContract
  → LLM 1회 언어화
```

즉 LLM 호출은 늘리지 않는다. AnswerContractBuilder는 graph traversal, score, selected graph, key/ref/profile 정보를 바탕으로 결정론적으로 작은 응답 계약을 만든다.

## 3. AnswerContract의 역할

AnswerContract는 다음을 포함한다.

```text
mode
continuity
max_sentences
key_labels
ref_labels
profile_labels
conclusion_lines
conflict_lines
evidence_lines
search_context_parts
response_policies
```

중요한 점:

```text
raw edge dump를 넘기지 않는다.
selected ConclusionGraph가 있으면 그 국소 그래프를 우선한다.
selected graph가 없으면 key/ref/profile 중심 최소 contract만 만든다.
ProfileRecallView는 긴 자연어 지시문이 아니라 mode/labels/confidence로 표현한다.
```

## 4. GraphToLang 변경

GraphToLang은 이제 아래만 수행한다.

```text
1. build_answer_contract(conclusion)
2. render_answer_contract(contract)
3. LLM에 작은 contract 전달
4. 자연어 답변 생성
```

LLM에게는 내부 필드명이나 그래프 덤프를 설명하지 말고, contract를 자연어 답변으로만 언어화하라고 지시한다.

## 5. 기대 효과

```text
- GraphToLang 프롬프트 길이 감소
- raw edge 수백 줄 전달 방지
- LLM이 그래프를 다시 해석하는 현상 완화
- 응답 길이와 형태가 더 안정화
- answer contract 생성을 위한 추가 LLM 호출 없음
```

## 6. 다음 작업

```text
1. AnswerContract mode 세분화
2. selected ConclusionGraph 품질 강화
3. SearchNeed primitive 추가로 search_fn 병목 완화
4. compact_structural_response에서 다음 쟁점 후보를 구조적으로 생성
```

