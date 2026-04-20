# MK6

작성: 2026-04-20  
상태: 아키텍처 설계 단계

---

## 정체성

MK6는 **개념 그래프 기반 인지 시스템**이다.

그래프를 "단어"가 아닌, **"그래프가 체감한 개념"** 으로서 정의한다.

MK5가 "언어체계에 올라간 장기기억 및 판단 구조"였다면,  
MK6는 **언어를 그래프 주소로 변환하고, 개념 그래프에서 사고한 뒤, 다시 언어로 출력**한다.

언어는 그래프 구조의 인터페이스다. 의미는 그래프 안에 있다.

---

## 핵심 변화 (vs MK5)

- `LangToGraph`: 언어 → 개념 포인터 집합 (탐색, ingest 아님)
- 검색은 Think 이후가 아니라 **LangToGraph의 EmptySlot을 채우는 과정** (Think 이전)
- 검색으로 그래프가 먼저 안정화 → **Think 루프 불필요**
- 노드는 텍스트 레이블이 아니라 **그래프 구조 위치**가 의미
- 공통부 추출 + 개념 분화로 **체감된 개념** 형성
- 파일/코드 도구 레이어 (2차)

---

## 파이프라인 요약

```
언어입력
  → LangToGraph → [ConceptPointer | EmptySlot]
  → EmptySlot: 검색으로 채우기 → 여전히 빈 경우 신규 ingest
  → Activation (ThoughtView — 이미 안정화된 그래프 기준)
  → Think (단일 패스 또는 최소 반복)
  → ConceptDifferentiation
  → ConclusionView
  → GraphToLang
  → 언어출력
  → Assistant Ingest (LangToGraph 경유)
```

---

## 아키텍처 문서

- 전체 구조: `docs/architecture/MK6_overview.md`
- LangToGraph 상세: `docs/architecture/lang_to_graph.md`
