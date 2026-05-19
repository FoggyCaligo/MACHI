# MK6 SurfaceFrame / AnswerContract 정책

작성: 2026-05-18  
정리: 2026-05-19  
상태: 현재 런타임 기준 문서

## 1. 문제

GraphToLang은 WorldGraph, TempThoughtGraph, raw ConclusionGraph를 직접 해석하면 안 된다.

그렇게 되면 LLM이 그래프 사고 결과를 언어화하는 것이 아니라, 내부 그래프 덤프를 다시 읽고 임의로 해석하는 구조가 된다.

## 2. 현재 결정

현재 런타임 경로는 다음 하나다.

```text
ConclusionView
  → build_answer_contract()
  → SurfaceFrame JSON
  → GraphToLang LLM 1회 언어화
```

구버전 텍스트형 AnswerContract 경로는 제거한다. GraphToLang에 전달되는 본체는 `SurfaceFrame JSON`이다.

## 3. SurfaceFrame의 역할

SurfaceFrame은 답변용 표면 프레임이다.

포함하는 정보는 다음과 같다.

```text
contract_type
source
response
focus
frames
conflicts
```

핵심 원칙:

```text
- raw graph dump를 넘기지 않는다.
- selected ConclusionGraph가 있으면 source=conclusion_graph가 된다.
- selected ConclusionGraph가 없으면 source=input_delta가 된다.
- GraphToLang은 SurfaceFrame에 없는 사실을 만들지 않는다.
- GraphToLang은 사용자 원문을 직접 보지 않는다.
```

## 4. source의 의미

`source`는 GraphToLang이 판단하는 값이 아니다.

```python
if selected_graphs:
    source = "conclusion_graph"
else:
    source = "input_delta"
```

따라서 `source=conclusion_graph`가 나온다면 문제 위치는 GraphToLang prompt가 아니라 `ConclusionView.selected_graphs` 생성 경로다.

## 5. 현재 GraphToLang 메시지 구조

현재 구조는 system/user 분리형이다.

```text
system message:
  GraphToLang 규칙만 포함

user message:
  SurfaceFrame JSON 코드블록
```

이 구조는 작은 로컬 모델에서 SurfaceFrame을 사용자 입력문처럼 오해하는 현상을 줄이기 위한 현재 기준이다.

## 6. 유지해야 할 것

```text
- SurfaceFrame edge는 제거하지 않는다.
- 문제는 edge 존재가 아니라, 어떤 edge가 selected ConclusionGraph body가 되느냐다.
- runtime goal edge는 activation pressure이지 answer body가 아니다.
- input graph와 conclusion graph는 분리되어야 한다.
```

## 7. 다음 작업 기준

이후 품질 문제를 고칠 때는 GraphToLang prompt를 먼저 늘리지 않는다.

우선 확인할 곳:

```text
MK6/core/thinking/activation.py
  - selected graph count
  - rejected graph count
  - rejection reason
  - selected edge endpoint
  - support_count
  - input boundary
```

`source=conclusion_graph`가 잘못 나온다면 selected graph 승격 기준을 고쳐야 한다.
