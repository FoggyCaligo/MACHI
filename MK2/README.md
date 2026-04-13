# MK2

MK2는 MK1의 Cognitive Partner 개념을 조금 더 **운영 가능한 로컬 에이전트 구조**로 정리하려던 단계입니다.

이 버전에서는 특히:

- system core
- user model
- persona support
- autonomy / approvals
- planner / tools

같은 계층이 분리되기 시작합니다.

## 이 버전의 핵심 관심사

MK2는 memory 자체를 깊게 밀어붙인 버전이라기보다, **에이전트가 어떤 규칙과 권한 아래 움직여야 하는가** 를 더 명확히 하던 단계에 가깝습니다.

중심 파일은 다음과 같습니다.

- `Machi/prompts/system_core.md`
  - 기본 운영 원칙
- `Machi/prompts/user_model.md`
  - 사용자 모델의 압축된 정의
- `Machi/prompts/persona_support.md`
  - 말투와 보조 방식
- `Machi/src/agent/`
  - planner, policy, approvals, autonomy, tools, memory

즉, MK2는 **"어떤 존재인가"** 에서 한 걸음 더 내려와  
**"어떤 규칙으로 움직이는가"** 를 다루는 버전입니다.

## 구조적으로 보면

이 단계에서는 다음 문제의식이 강하게 보입니다.

- 사용자의 결정권은 어디까지 보장할 것인가
- 승인 없는 행동은 어디까지 막을 것인가
- 자율성과 통제의 균형을 어떻게 둘 것인가
- memory는 어떤 최소 형태로 유지할 것인가
- UI와 에이전트 동작을 어떻게 연결할 것인가

그래서 MK2는 MACHI 전체 흐름에서 **운영 규칙과 에이전트 거버넌스를 다듬는 중간 단계**로 이해하면 가장 자연스럽습니다.

## MACHI 전체에서의 위치

정리하면 MK2는:

- MK1의 철학을 더 실행 가능한 규칙으로 옮기던 단계
- MK3의 로컬 도구형 에이전트로 가기 전 단계
- MK4처럼 evidence-first memory를 밀어붙이기 전, agent operating model을 정리하던 단계

에 해당합니다.
