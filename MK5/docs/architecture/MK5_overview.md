# MK5 Overview

업데이트: 2026-04-16

## 한 줄 요약
MK5는 입력을 그래프에 적재하고, 활성 그래프에서 사고/판정을 수행한 뒤, 결론만 언어화하는 edge-first 파이프라인이다.

## 파이프라인
1. Ingest
   - `GraphIngestService`가 node/edge/pointer/event를 기록
2. Activation
   - `ActivationEngine`이 현재 질의 중심 `ThoughtView` 구성
3. Thinking
   - contradiction 감지
   - trust/pressure 갱신
   - marker edge 누적
   - `StructureRevisionService` 규칙 기반 revision 실행
4. Conclusion
   - `CoreConclusion`과 `DerivedActionLayer` 생성
5. Verbalization
   - 결론을 사용자 응답으로 언어화
6. Assistant ingest
   - 최종 응답도 다시 그래프에 적재

## Edge-first 상태
- `edge_family/connect_type/relation_detail` 3축으로 의미를 표현한다.
- connect type 제안은 즉시 스키마 확장 대신 proposal로 누적 후 승격한다.
- temporary edge는 session/topic 전환 정책으로 정리한다.

## 운영 튜닝
- revision 규칙은 override 파일로 런타임에서 조정 가능
- 추천/적용 도구:
  - `tools/revision_rule_report.py`
  - `tools/revision_rule_apply_overrides.py`
- 자동화:
  - `tools/run_revision_rule_override_job.ps1`
  - `tools/setup_revision_rule_scheduler.ps1`
