# MK4 SQLite Skeleton

이 프로젝트는 관계형 개인화를 위한 SQLite 기반 메모리 시스템의 골격입니다.

핵심 원칙:
- memory is not append-only
- memory is updated, consolidated, compressed, or discarded
- correction은 profile을 갱신하지만 history는 제한적으로 유지
- recall은 1차 요약, 2차 원문 확장

## 디렉토리 구조
- `app/`: API / 오케스트레이션 / 에이전트
- `memory/`: DB 접근, 저장소, retrieval, 정책, 요약
- `tools/`: LLM/Ollama 및 검색
- `prompts/`: 시스템 프롬프트 및 prompt builder
- `data/memory.db`: SQLite 데이터 파일

## 현재 포함된 것
- `schema.sql`: SQLite 테이블 정의
- 각 계층의 Python 골격 파일

## 구현 순서 권장
1. `memory/db.py`로 DB 초기화
2. `stores/*`에 CRUD 구현
3. `policies/*`에 correction / retention / extraction 규칙 구현
4. `retrieval/*`에 response/recall/update retrieval 구현
5. `app/orchestrator.py`에서 전체 흐름 연결
6. `tools/ollama_client.py`와 `app/agent.py` 연결
