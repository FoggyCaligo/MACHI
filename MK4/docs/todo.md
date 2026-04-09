# todo.md

이 문서는 `docs/다음_작업.txt`와 이번 대화에서 새로 드러난 수정 필요사항을 합쳐,
**현재 코드 기준**으로 다시 정리한 작업 목록이다.

원칙:
- **아직 안 되었거나 부족한 것**은 위쪽에, **중요도 순서대로** 1줄씩 배치
- **이미 코드에 반영된 항목**은 아래쪽에 취소선 + 회색으로 정리
- “완료”는 최종 완성 의미가 아니라, **코드에 일단 반영됨** 의미일 수 있음

---

## 우선 처리 필요

- `profile_attachment_ingest_service.py`의 `self._build_extract_messages()` 호출은 현재 **정의 없는 메서드 호출 버그**이므로 즉시 수정 필요
- `memory_classification_policy.py`의 규칙 기반 신호(1인칭/확신/배경 등) 제거 또는 대폭 축소 필요
- recent source / DB / 과거 대화를 **모델이 필요 시 찾아보는 source lookup layer** 설계 및 구현 필요
- recent source는 **최근 3개 유지 + 사용자 발화 4턴 미사용 시 후보 제외** 정책으로 구현 필요
- `reply_guard.py`는 현재 남은 구조 판단 역할만 유지하고, 이후 source lookup layer와의 관계 재정리 필요
- `app/api.py`에서 최근 source를 질문마다 자동 검사하지 말고, **모델/구조가 필요하다고 판단할 때만 조회**하는 방식으로 재설계 필요
- `passage_selection_service.py`는 현재 임베딩 기반으로 전환됐지만, **selection 목적 함수(`PROFILE_SELECTION_QUERY`)의 장기 유지 여부** 검토 필요
- `profile_attachment_ingest_service.py`의 follow-up / answer / extract 흐름을 다시 점검해서, 남은 문자열 분기/구버전 호출/누락 메서드 참조 제거 필요
- 일반 채팅 답변 경로에서 **짧음 / `...` / 반복 / 얼버무림 / 모르는 걸 모른다고 못 하는 문제**를 끝까지 재현 테스트하며 수정 필요
- `ResponseRunner`와 프론트 렌더링 경로를 함께 점검해서, continuation이 실제 UI에서 정상 반영되는지 검증 필요
- 텍스트 첨부 후 후속 질문에서, 직전 source를 자동 병합하지 않고도 **필요 시 참조 가능한 구조**를 설계해야 함
- `README.md`는 현재 코드가 한 단계 더 정리된 뒤, **코드 기준**으로 다시 작성 필요
- 전체 파일 기준으로 남은 하드코딩/매크로 응답/중복 상수/레거시 참조 재탐색 필요
- 실제 속도/품질 측정 루프(응답시간, topic 유지율, attach 정확도, general 누적량, confirmed 승격 빈도) 추가 필요
- 미사용 함수/변수/파일 재탐색 후 삭제 필요

---

## 적용됐거나 1차 반영된 것

- <span style="color:#888">~~기준 작업본을 ZIP이 아니라 현재 작업본 기준으로 이어가는 원칙 정리~~</span>
- <span style="color:#888">~~UI에서 Ollama 모델 선택 가능~~</span>
- <span style="color:#888">~~`/models` API와 `/chat`의 model 전달 경로 연결~~</span>
- <span style="color:#888">~~텍스트 첨부 프로필 요청을 preview-first에서 update-first로 전환~~</span>
- <span style="color:#888">~~`ProfileAttachmentIngestService` 기반 source → evidence → sync → answer 흐름 1차 반영~~</span>
- <span style="color:#888">~~첨부 텍스트 최종 답변을 코드 템플릿이 아니라 모델 생성으로 변경~~</span>
- <span style="color:#888">~~Ollama `done_reason == length` 감지 추가~~</span>
- <span style="color:#888">~~memory contamination 방어용 필터 1차 추가~~</span>
- <span style="color:#888">~~system prompt를 사용자 하드코딩보다 운영 원칙 중심으로 얇게 정리하는 방향 반영~~</span>
- <span style="color:#888">~~topic 객체화(`topics` 테이블, `topic_id` 중심 구조) 1차 반영~~</span>
- <span style="color:#888">~~active topic 유지 / attach / create 뼈대 반영~~</span>
- <span style="color:#888">~~`general` 기본 주입 제외 및 90일 TTL 방향 반영~~</span>
- <span style="color:#888">~~`project_id`는 제거하지 않고 출처 축으로 유지하기로 결정~~</span>
- <span style="color:#888">~~`ResponseRunner` 공용화 1차 반영~~</span>
- <span style="color:#888">~~`MemoryClassificationPolicy` 공용화 1차 반영~~</span>
- <span style="color:#888">~~`EvidenceExtractionService` 공용화 1차 반영~~</span>
- <span style="color:#888">~~`PassageSelectionService` 공용화 1차 반영~~</span>
- <span style="color:#888">~~`passage_selection_service.py`를 문자열 점수표 중심에서 임베딩 중심 구조로 1차 전환~~</span>
- <span style="color:#888">~~`reply_guard.py`의 완성형 한국어 매크로 응답 제거~~</span>
- <span style="color:#888">~~`app/api.py`의 블로그/글/화자/직전 파일 문자열 트리거 제거~~</span>
- <span style="color:#888">~~텍스트 첨부 라우팅을 문자열 규칙에서 모델 판단 기반으로 1차 전환~~</span>
- <span style="color:#888">~~중복된 언어 신호 상수(`FIRST_PERSON_MARKERS` 등)를 공통 파일로 모으는 1차 정리~~</span>
- <span style="color:#888">~~prompt에서 블로그/특정 도메인 하드코딩 표현 일부 일반화~~</span>
- <span style="color:#888">~~프롬프트 경량화 1차 반영~~</span>

---

## 보류/결정 완료 메모

- `passage_selection_service.py`의 **기존 휴리스틱은 보조로서도 유지하지 않음**
- recent source 정책은 **최근 3개 유지 + 사용자 발화 4턴 미사용 시 후보 제외**
- 텍스트 첨부 라우팅 fallback은 일단 유지
- `project_id`는 topic으로 대체하지 않고 출처 축으로 유지
- 전체 재빌드보다는 **핵심 계층 재구현/재정렬**이 더 적절하다고 판단
