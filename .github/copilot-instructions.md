# MK5 Agent Rules

## 목적
이 프로젝트의 목적은 그럴듯한 답변 생성보다, 그래프 기반 의미/기억 구조의 정합성을 유지하는 것이다.

## 최우선 원칙
- 문자열이 아니라 구조가 의미를 말하게 하라.
- 임시 봉합보다 구조 정리를 우선하라.
- 답변 품질보다 정책 준수 여부를 먼저 보라.
- 큰 수정보다 정확한 최소 수정을 택하라.

## 절대 금지
- `kind`, `type`, `category` 등으로 node의 본질을 판별하지 말 것
- 자유 텍스트(`note`, `text`, `summary`, `label`)를 파싱해 의미를 복원하지 말 것
- 특정 단어/문구 포함 여부로 relation 의미를 판정하지 말 것
- direct access 성공만으로 search 필요성을 꺼버리지 말 것
- placeholder/빈 node를 영구 상태로 남기지 말 것
- 버그를 임시 예외 분기로 덮지 말 것
- 제거한 개념을 다른 이름으로 우회 부활시키지 말 것

## 구조 원칙
- node는 존재 단위이지 종류 단위가 아니다.
- 의미 차이는 relation, structured data, provenance, confidence/status에서 드러나야 한다.
- search는 존재 확인이 아니라 의미 보강 과정이다.
- existing node가 있어도 search가 필요할 수 있다.
- placeholder는 enrich 대상이다.
- extraction / normalization / apply / response의 책임을 섞지 말 것
- profile / topic / general / relation / evidence는 서로 다른 책임을 가진다.

## 작업 절차
1. 먼저 문제를 분석하라.
2. 정책 위반 여부를 확인하라.
3. 수정 계획을 먼저 제시하라.
4. 그 다음 최소 범위로 수정하라.
5. 수정 후 영향과 리스크를 정리하라.

## 수정 전 체크
- 이 변경은 구조를 개선하는가, 아니면 분기를 추가하는가?
- 의미 판정을 다시 문자열에 의존하게 만들지 않는가?
- placeholder가 영구 빈 node로 남는 경로를 만들지 않는가?
- kind 역할의 구조를 우회 재도입하지 않는가?
- search / store / apply 흐름이 더 명확해지는가?

## 기본 태도
- 추측보다 근거
- 임시 봉합보다 구조 정리
- 과도한 확신보다 검증 가능한 설명
- 많은 수정보다 정확한 수정