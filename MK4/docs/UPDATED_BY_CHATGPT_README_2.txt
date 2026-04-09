이번 업데이트에서 반영한 핵심

1. 입력 자료를 project / profile로 강하게 mode 분리하지 않고,
   ZIP 업로드는 기본적으로 모두 artifact/project ingest로 처리하도록 바꿈.

2. artifact/project ingest 이후,
   텍스트 문서(.txt, .md, .markdown, .rst 등)가 있으면
   project_profile_evidence 테이블에 프로필 후보 evidence를 자동 추출/저장하도록 추가.

3. 같은 project_id에 대해 질문할 때,
   질문이 프로필/성향 관련이면 code chunk 검색보다 profile evidence 답변을 우선 사용.
   예시 질문:
   - 내 성향을 이 자료 기준으로 말해줘
   - 이 프로젝트를 하면서 드러난 내 스타일은 뭐야?
   - 이 문서들로 볼 때 내가 중요하게 여기는 기준은 뭐야?

4. UI 단순화
   - mode 선택 제거
   - ZIP은 artifact/project 업로드
   - 텍스트 파일은 현재 질문 참고 자료
   - project_id 자동 저장/표시

주의
- 아직 'profile evidence -> confirmed profile 자동 반영'까지는 구현하지 않았다.
  지금은 evidence/candidate 계층까지만 추가했다.
- 즉, 프로젝트를 하면서 profile을 곧바로 덮어쓰는 구조는 일부러 막아두었다.
  오염을 줄이기 위한 설계다.
