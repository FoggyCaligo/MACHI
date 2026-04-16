# MK5 다음작업 로드맵 (중장기)

업데이트: 2026-04-16

## P0
1. revision 실행기 edge-first 전환
   - revision marker edge 누적 임계치로 deactivate/merge를 실행
2. contradiction/revision 규칙을 `edge_family + connect_type + relation_detail.kind` 기준으로 명확화
3. identity/topic continuity 회귀 테스트 세트 확장

## P1
1. connect_type 승격 정책 고도화
   - per-kind threshold, 세션/전역 근거 분리, 승격 롤백 정책
2. as-of 시점 질의 규칙 구체화
3. 검색 근거가 revision marker로 이어지는 정책 강화

## P2
1. 장기 기억 정합성 정책
   - 일회성 evidence vs 장기 구조 분리
2. graph commit/update 리포트 자동화
3. 품질 측정 배치
   - groundedness / consistency / continuity

## 참고
- 단기 실행 목록은 [현재작업.txt](/c:/Users/bigla/Documents/git/MACHI/MK5/docs/todo/현재작업.txt)에서 관리한다.
