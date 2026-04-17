# MK5 Slimmed Runtime

이 ZIP은 최신 기준본에서 핫패스를 다이어트한 버전입니다.

## 런타임에서 제거/비활성화한 층
- PatternDetector
- IntentManager
- ConceptDifferentiationService
- TemporaryEdgeService
- ModelFeedbackService
- ModelEdgeAssertionService
- ConnectTypePromotionService
- revision rule analytics / tuner / scheduler / override automation

## 유지한 핵심
- GraphIngestService
- ActivationEngine (seed/neighbor/pointer expansion)
- ThoughtEngine의 최소 루프
  - ContradictionDetector
  - TrustManager
  - StructureRevisionService
  - ConclusionBuilder
- StructureRevisionService 내부의 node merge / pointer rewrite
- edge connect_type의 핵심 축
  - flow / neutral / opposite / conflict
- SearchSidecar와 검색 ingest 경로
- Verbalizer

## 구현 방식
- 핫패스 wiring 제거
- 관련 서비스 파일/도구/테스트 일부 제거
- ThoughtEngine은 최소 IntentSnapshot만 직접 구성
- ActivationEngine은 pattern detection 없이 local graph만 구성

## 주의
- 이전에 관련 기능을 검증하던 테스트/운영 스크립트 일부는 같이 제거됨
- 답변 품질 보조층이 빠졌기 때문에, 이후 개선은 핫패스에 새 기능을 덕지덕지 붙이기보다 핵심 루프 설계를 다듬는 방향이 적합함
