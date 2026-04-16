# MK5 전체정리 (Master)

Updated: 2026-04-16

## 1. 프로젝트 정의
MK5는 graph-first cognition 시스템이다.  
입력을 그래프에 반영하고, activation/thinking/conclusion을 그래프 중심으로 수행한 뒤 verbalization을 수행한다.

## 2. 현재 아키텍처
1. ingest: `GraphIngestService`
2. activation: `ActivationEngine`
3. thinking: `ThoughtEngine` (contradiction/trust/revision/intent/conclusion)
4. search enrichment: `SearchSidecar` + re-think
5. verbalization: `Verbalizer`
6. assistant reply ingest

## 3. 최근 핵심 반영
- `ModelFeedbackService` 연동 (기존 엣지 support/conflict 반영)
- `ModelEdgeAssertionService` 연동 (신규 구조 엣지 생성/강화)
- concept edge 우선 + concept 2-hop activation 확장
- connect_type 정책 정리:
  - allowlist: `flow`, `neutral`, `opposite`, `conflict`
  - 비허용 타입은 `proposed_connect_type`으로 후보 축적

## 4. 문서 체계
- 이 문서: 단일 마스터 문서
- 중장기 계획: [MK5_다음작업_로드맵.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/MK5_다음작업_로드맵.md)
- 단기 실행: [현재작업.txt](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/현재작업.txt)
- 검색 전략: [MK5_검색_및_검증_전략.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/MK5_검색_및_검증_전략.md)
- 인수인계: [MK5_handoff.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/handoff/MK5_handoff.md)

## 5. 설계 문서 위치 (architecture/)
- [MK5_overview.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/architecture/MK5_overview.md)
- [thought_flow.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/architecture/thought_flow.md)
- [graph_model.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/architecture/graph_model.md)
- [trust_revision_rule.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/architecture/trust_revision_rule.md)
- [identity_temporal_design.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/architecture/identity_temporal_design.md)
- [edge_family_connect_type_design.md](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/architecture/edge_family_connect_type_design.md)
