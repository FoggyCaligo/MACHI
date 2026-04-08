이번 압축본에 반영된 실제 변경 사항

1. app/api.py
- initialize_database() + init_project_tables()를 lifespan에서 같이 실행
- /ui 정적 채팅 UI 추가
- /chat에서 multipart/form-data 처리 유지
- ZIP 업로드: project 분석 또는 mode=profile_extract 처리
- 일반 텍스트 파일 첨부: 현재 메시지에 본문을 합쳐서 일반 대화로 전송
- 일반 대화 응답을 중첩 reply가 아니라 평탄한 reply 문자열로 반환
- /recall 유지

2. app/static/chat.html / chat.css / chat.js 추가
- Enter 전송
- Shift+Enter 줄바꿈
- 파일 첨부 버튼
- mode 선택(project / profile_extract)
- project_id 입력칸

3. app/orchestrator.py
- handle_chat 내부의 self.agent.respond(...) 중복 호출 1회 제거

4. 이미 ZIP에 들어 있던 변경 사항은 유지됨
- tools/ollama_client.py의 think=false / empty reply 분류 로직
- response_retriever.py 경량화
- response_builder.py compact context 구성
- raw_message_store.py 빈 문자열 저장 방지
- 긴 system_prompt 유지

아직 코드로 반영되지 않은 설계 논의
- 모든 자료를 단일 artifact/document로 ingest하고,
  project context와 profile evidence를 동시에 추출하는 통합 파이프라인
이건 이번 압축본에는 설계만 논의되었고 실제 코드 리팩터링은 아직 반영하지 않았습니다.
