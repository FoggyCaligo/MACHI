# MK5 전체정리 (마스터 문서)

업데이트: 2026-04-16

## 1. 현재 정체성
MK5는 그래프 중심 인지 시스템이다.
LLM은 구조 판정/제안/언어화에 참여하는 하위 모듈이고, 장기 상태와 판단 근거의 중심은 그래프다.

## 2. 실행 파이프라인
1. User ingest
2. Local activation (`ThoughtView`)
3. Thinking (contradiction → trust update → revision)
4. Search sidecar + 재사고
5. Conclusion + action layer
6. Verbalization
7. Assistant ingest

## 3. 현재 그래프 철학
- Edge의 본체는 `edge_family + connect_type + 방향 + 상태값`이다.
- `connect_type` 기본 집합은 `flow | neutral | opposite | conflict`다.
- `relation_detail`은 구조 의미의 본체가 아니라 보조 메타데이터 층이다.
- `kind`와 `connect_semantics` 중심 설계는 현재 방향과 맞지 않는다.

## 4. Node / Edge 해석
- Node는 가능한 한 일반 node 하나를 기본으로 둔다.
- 개념 분화는 `concept/flow`로 읽는다.
- 이름/호칭/표상 군집은 `concept/neutral`로 읽는다.
- 실제 관계/상태는 `relation/*`로 읽는다.
- 충돌은 `connect_type='conflict'`와 상태값으로 본다.

## 5. 사고와 조회
- 사고는 전체 그래프가 아니라 국부 활성화 그래프에서 한다.
- 하지만 node/edge는 direct access로 직접 조회할 수 있어야 한다.
- 즉 reasoning path와 lookup path를 분리한다.

## 6. 시간성
- `3월의 Machi`, `4월의 Machi`처럼 새 노드를 계속 만들지 않는다.
- 현재 node/edge와 bounded append-only event log를 바탕으로, 필요할 때 과거 시점의 국소 그래프를 재형성한다.

## 7. 최근 방향성 수정
- `kind` 의존 축소/제거
- 일반 node 중심으로 재정렬
- `conflict` connect type 도입
- local activation + direct access 병행
- bounded log 기반 재형성 방향 확정

## 8. 현재 남은 우선과제
1. 문서/코드 전반의 `kind` 의존 제거
2. direct access 계약 정리
3. bounded log + 기준시점 재형성 계약 정리
4. conflict edge 생성/강화 정책 정교화
5. ingest에서 `concept/flow`, `concept/neutral`, `relation/conflict` 형성 강화

## 9. 문서 체계
- 마스터: `docs/guid/MK5_전체정리.md`
- 아키텍처 상세: `docs/architecture/*`
- 핸드오프: `docs/handoff/MK5_handoff.md`
- 단기 실행: `docs/todo/현재작업.txt`
- 작업 원칙: `docs/todo/작업수칙.md`
