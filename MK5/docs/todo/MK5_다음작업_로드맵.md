# MK5 다음작업 로드맵 (중장기)

업데이트: 2026-04-16

## P0
1. 코드 전반의 `kind` / `connect_semantics` 의존 제거
2. `conflict` connect type을 중심으로 contradiction/revision 재정렬
3. direct access 경로와 local activation 경로의 계약 정리
4. bounded log 기반 기준시점 재형성 계약 정리

## P1
1. ingest에서 `concept/flow`, `concept/neutral`, `relation/conflict` 형성 강화
2. connect_type 승격 정책을 문자열 ontology가 아니라 구조/반복 패턴 기준으로 정리
3. identity/topic continuity 회귀 테스트 세트 확장

## P2
1. 장기 기억 정합성 정책
   - 일회성 evidence vs 장기 구조 분리
2. graph commit/update 리포트 자동화
3. 품질 측정 배치
   - groundedness / consistency / continuity

## 참고
- 단기 실행 목록은 `docs/todo/현재작업.txt`에서 관리한다.
