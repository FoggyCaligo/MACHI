# Trust Revision Rule

업데이트: 2026-04-16

## 기본 원칙
- 단발 충돌로 즉시 구조를 뒤엎지 않는다.
- 충돌/압력/trust 저하가 누적될 때 revision 후보로 올린다.
- 근거는 이벤트 로그뿐 아니라 revision-purpose edge로도 남긴다.

## 현재 규칙(운영 중)
`TrustManager`가 contradiction signal을 받으면:
- 원본 edge에 `conflict_count`, `contradiction_pressure`, trust 변화를 반영
- 필요 시 `revision_candidate_flag`를 세팅
- 동시에 revision-purpose edge를 기록
  - `purpose=revision`
  - `kind=conflict_assertion`
  - `connect_type=conflict`

revision candidate 판단 임계:
- `contradiction_pressure >= 2.0`
- 또는 `conflict_count >= 2`
- 또는 `trust_score <= 0.42`

## Structure Revision 단계
`StructureRevisionService`는 후보 edge를 리뷰하고 revision marker를 기록한다.

- 보류 시:
  - `kind=revision_pending`
  - `connect_type=neutral`
- deactivation 실행 시:
  - `kind=deactivate_candidate`
  - `status=executed`
- merge 실행 시:
  - `kind=merge_candidate`
  - `status=executed`

실행 임계(현재):
- deactivate:
  - `trust_score <= 0.2` 또는 `pressure >= 4.0` 또는 `conflict_count >= 4`
- merge:
  - duplicate-like node 조건 + revision gate 통과

## 다음 단계(진행 예정)
- `revision_candidate_flag` 중심에서 점진적으로 marker edge 중심 실행기로 전환
- family/type/kind 조합별 deterministic rule 테이블화
- merge/deactivate 실행 이력과 marker edge를 더 강하게 연결
