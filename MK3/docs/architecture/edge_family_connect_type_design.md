# Edge Family And Connect Type Design

업데이트: 2026-04-16

## Core Shape
- `edge_family`: `concept` | `relation`
- `connect_type`: `flow` | `neutral` | `opposite` | `conflict`
- `relation_detail`: note/provenance/proposal 등 보조 정보

## 이유
- behavior 축(`family/type`)을 본체 의미론으로 두고, relation_detail은 보조 정보로만 둔다.
- 동일 node pair에도 의미가 다르면 다중 edge 공존을 허용한다.

## 새로운 connect_type 제안 경로
모델이 allowlist 밖 타입을 제안하면 즉시 확장하지 않고:
- 저장은 `connect_type=neutral`
- `relation_detail.proposed_connect_type`에 후보 보존
- `relation_detail.proposal_reason` 기록

## 승격 정책(현재 구현)
- `ConnectTypePromotionService`가 후보를 스캔한다.
- 단순 count가 아니라 가중치 점수 기반으로 승격한다.
  - support_count
  - trust_score
  - inferred/source_type/claim_domain 가중치

## 쓰기 경로
- `ModelFeedbackService` + `GraphCommitService`: 기존 edge support/conflict 업데이트
- `ModelEdgeAssertionService`: 구조 edge 생성/강화
- `RevisionEdgeService`: revision-purpose marker edge 생성/강화

## 남은 과제
1. 승격 정책을 connect_type별로 더 세분화
2. revision rule에서 family/type/상태값 해석 규칙 강화
3. 같은 node pair 다중 edge의 우선순위/읽기 규칙 명문화
