# MK5 전체정리 (Master)

업데이트: 2026-04-16

## 1. 프로젝트 정의
MK5는 그래프를 사고의 중심으로 두는 graph-first cognition 시스템이다.  
입력은 그래프에 누적되고, activation/thinking/revision을 거친 뒤 verbalization이 마지막에 수행된다.

## 2. 현재 파이프라인
1. ingest: `GraphIngestService`
2. activation: `ActivationEngine` (concept 2-hop 포함)
3. thinking: `ThoughtEngine` (contradiction/trust/revision/intent/conclusion)
4. search enrichment: `SearchSidecar` + re-think
5. verbalization: `Verbalizer`
6. assistant reply ingest

## 3. 최근 반영 핵심
- `connect_type`: `flow`, `neutral`, `opposite`, `conflict`
- `ModelFeedbackService` + `GraphCommitService` 연동
- `ModelEdgeAssertionService` 연동
- `proposed_connect_type` 승격 정책 구현
  - 단순 카운트가 아니라 `support + trust + source/domain` 가중치 기반
- `revision-purpose edge` 표준화 도입
  - `relation_detail.purpose = "revision"`
  - `kind = conflict_assertion | revision_pending | deactivate_candidate | merge_candidate`
  - `TrustManager`, `StructureRevisionService`가 revision marker edge를 기록

## 4. 현재 구조의 의미
- 충돌은 더 이상 이벤트 로그에만 남지 않고 `connect_type=conflict`와 revision marker edge로 그래프에 남는다.
- 구조 개정 판단은 기존 pressure/trust 기준을 유지하되, 근거를 그래프 edge로 명시한다.
- 모델의 비허용 `connect_type` 제안은 즉시 확장하지 않고 `proposed_connect_type`으로 누적 후 승격한다.

## 5. 문서 체계
- 단기 실행: [현재작업.txt](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/todo/현재작업.txt)
- 중장기 로드맵: [MK5_다음작업_로드맵.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/todo/MK5_다음작업_로드맵.md)
- 검색/검증 전략: [MK5_검색_및_검증_전략.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/guid/MK5_검색_및_검증_전략.md)
- 인수인계: [MK5_handoff.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/handoff/MK5_handoff.md)
