# MK5 Skeleton

이 폴더는 MK5의 **프로젝트 구조 초안**과 **SQLite용 schema.sql 초안**을 담은 골격이다.

핵심 원칙:
- 모든 입력은 `chat_messages`로 유입된다.
- 장기 기억은 `nodes` + `edges` 그래프로 저장된다.
- 그래프 변경의 이유와 역사는 `graph_events`로 남긴다.
- 중복 저장 대신 `node_pointers`로 참조를 표현한다.
- 기본은 기존 구조 보존이지만, 반복 반례는 신뢰도를 낮추고 구조 교체를 유도할 수 있다.

## 핵심 DB 테이블
- `chat_messages`: 원본 대화/입력 이벤트
- `nodes`: 개념 노드
- `edges`: 관계 엣지
- `graph_events`: 그래프 변화 이력
- `node_pointers`: 중복 대신 참조

## 현재 상태
- 코드 구현은 비어 있거나 최소 placeholder만 있다.
- 실제 구현 시작점은 `storage/schema.sql`과 `core/` 하위 역할 분리이다.
