# MK1

MK1은 MACHI의 가장 초기 단계로, **Cognitive Partner 개념**과 **인지 구조 자체를 어떻게 설계할 것인가**를 탐색하던 버전입니다.

이 폴더의 핵심은 완성된 앱이라기보다:

- 사용자를 어떤 방식으로 이해할 것인가
- AI를 단순 응답기가 아니라 어떤 존재로 둘 것인가
- 기억, 패턴, 의도, 세계 구조를 어떻게 나눌 것인가
- 더 장기적으로는 LLM 이후의 인지 아키텍처를 어떻게 상상할 것인가

를 실험한 문서와 초기 스크립트에 있습니다.

## 이 버전의 성격

MK1은 MACHI의 **철학적 출발점**에 가깝습니다.

- `machi/memory/identity.md`
  - Cognitive Partner가 어떤 관계와 역할을 가져야 하는지
- `machi/memory/patterns.md`
  - 사용자 사고 패턴과 개입 규칙
- `machi/prompts/wake_up_prompt.txt`
  - 파트너의 부트로더에 가까운 프롬프트
- `idea_brainstorming/`
  - 그래프 기반 인지 구조, 구조 학습, 자아/세계 분리 같은 상위 아키텍처 아이디어

즉, MK1은 "좋은 챗봇을 만들자"보다 **"어떤 인지 시스템을 만들 것인가"** 를 먼저 묻는 단계입니다.

## 코드 쪽에서 보면

코드와 스크립트도 조금 들어 있지만, 현재 기준으로는 실행형 메인라인이라기보다 **초기 memory 실험과 CLI 흐름** 정도로 보는 것이 맞습니다.

- `machi/scripts/chat.py`
- `machi/scripts/save_log.py`
- `machi/scripts/summarize.py`

## MACHI 전체에서의 위치

MACHI 전체 흐름에서 MK1은:

- Cognitive Partner 개념의 출발점
- 사용자 모델과 관계 규칙의 초안
- memory보다 더 위에 있는 인지 구조 아이디어의 발화점

에 해당합니다.

실제 구현이 가장 진전된 현재 축은 `MK4`이지만, MACHI가 왜 지금 방향을 갖게 되었는지는 MK1 문서들을 보면 가장 잘 드러납니다.
