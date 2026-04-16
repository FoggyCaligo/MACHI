# MK5 Handoff

업데이트: 2026-04-16

## 현재 기준 상태
이번 세션 이후의 상위 기준은 아래와 같다.

- `edge_type` 중심 설계는 버린다.
- `relation_detail.kind` / `connect_semantics` 중심 해석도 현재 철학과 맞지 않는다.
- Edge의 본체는 `edge_family + connect_type + 방향 + 상태값`이다.
- Node는 과도한 세분화보다 일반 node 하나를 기본으로 둔다.
- 사고는 local activation에서 하고, 특정 node/edge는 direct access로 조회 가능해야 한다.
- 과거 시점은 새 노드를 만들지 않고 bounded event log로 재형성한다.

## 지금 핵심 위험
최근 진척 중 revision rule override, promotion, model-edge-assertion 쪽은 늘었지만,
문서/코드 일부가 다시 `kind`와 문자열 의미 라벨에 기대기 시작했다.
이건 현재 MK5 철학과 어긋나는 가장 큰 리스크다.

## 지금 당장 문서 기준으로 맞춰야 하는 것
1. `kind` / `connect_semantics`를 본체 의미론에서 제거
2. `conflict`를 connect type으로 정식 반영
3. `node_kind` 과세분화보다 일반 node 방향으로 재정렬
4. local activation / direct access / bounded log / 기준시점 재형성 계약 명시

## 다음 우선순위
1. 코드 전반의 `kind` 의존 제거
2. direct access 경로와 activation 경로 계약 정리
3. bounded log 기반 기준시점 재형성 계약 정리
4. conflict edge 생성/강화 정책 정교화
5. ingest에서 `concept/flow`, `concept/neutral`, `relation/conflict` 형성 강화

## 운영/검증 메모
- revision rule override 자체는 운영 도구로 남길 수 있다.
- 다만 override가 현재 상위 철학을 덮어쓰면 안 된다.
- Windows pytest temp/cache 권한 이슈는 간헐적으로 남아 있다.

## 현재 기준 문서
- 마스터: `docs/guid/MK5_전체정리.md`
- 개념: `docs/guid/개념업데이트_정체성_시간성_그래프.md`
- 아키텍처: `docs/architecture/*`
- 단기 실행: `docs/todo/현재작업.txt`
- 작업 원칙: `docs/todo/작업수칙.md`
