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




/////////////////////////////////////////////





# todo.md

이 문서는 아래 3가지를 합쳐서 다시 정리한 **현재 작업본 기준** TODO 문서다.

- 기존 `todo.md`
- `다음_작업.txt`
- 최근 대화에서 새로 드러난 구조 문제 / 수정 필요사항

정리 원칙:
- **위쪽**에는 아직 안 되었거나 부족한 것들을 **중요도 순서대로 한 줄씩** 둔다.
- **아래쪽**에는 코드에 1차 반영된 것들을 **취소선 + 회색**으로 둔다.
- “반영됨”은 최종 완성 의미가 아니라, **코드에 일단 들어간 상태**를 뜻할 수 있다.
- 이 문서는 **설계 철학**과 **현재 코드 상태**를 동시에 반영한다.

---

## 최우선 처리 필요

- `memory_classification_policy.py`를 **규칙 해석기에서 정책층으로 축소**해야 한다. 현재 1인칭/확신/배경 같은 문자열 신호에 의존하고 있다.
- recent source / DB / 과거 대화를 **모델이 필요할 때만 찾는 source lookup layer**를 설계하고 구현해야 한다.
- recent source는 **최근 3개 유지 + 사용자 발화 4턴 미사용 시 후보 제외** 정책을 구현해야 한다.
- `reply_guard.py`는 지금 남아 있는 **구조 판단 역할만 유지**하고, source lookup layer가 들어오면 관계를 다시 정리해야 한다.
- `app/api.py`에서 recent source를 질문마다 자동 검사하지 말고, **모델/구조가 필요하다고 판단할 때만 조회**하는 방식으로 재설계해야 한다.
- 일반 채팅 답변 경로에서 **짧음 / `...` / 반복 / 얼버무림 / 모르는 걸 모른다고 못 하는 문제**를 끝까지 재현 테스트하며 수정해야 한다.
- `ResponseRunner`와 프론트 렌더링 경로를 함께 점검해서, continuation이 실제 UI에 정상 반영되는지 검증해야 한다.
- 텍스트 첨부 후 후속 질문에서, 직전 source를 자동 병합하지 않고도 **필요 시 참조 가능한 구조**를 만들어야 한다.
- `profile_analysis/services/project_profile_evidence_service.py`의 **실제 참조 여부를 확인**하고, 레거시/중복 파일이면 정리해야 한다.
- 중복된 기능·변수·함수·래퍼를 전수 조사해서, **공통 레이어로 끌어올리고 각 경로가 그것을 쓰도록 하나씩 전환**해야 한다.
- 남아 있는 하드코딩 / 매크로 응답 / 도메인 특정 문자열 의존 / 중복 상수 / 레거시 참조를 전체 파일 기준으로 다시 찾아내야 한다.
- 실제 속도/품질 측정 루프(응답시간, topic 유지율, attach 정확도, general 누적량, confirmed 승격 빈도)를 추가해야 한다.
- 미사용 함수/변수/파일을 재탐색하고 삭제해야 한다.
- `README.md`는 현재 코드가 한 단계 더 정리된 뒤, **코드 기준**으로 다시 작성해야 한다.

---

## 높은 우선순위

- artifact / profile attachment 경로를 topic router 철학에 더 깊게 맞춰야 한다.
- confirmed / candidate / general 경계를 전 경로에서 일관되게 통일해야 한다.
- correction 기반 재구성을 profile 수준에서 **topic 수준까지 확장**해야 한다.
- 새 topic 생성 제약을 프롬프트 수준을 넘어 **후처리 단계까지** 넣어야 한다.
- artifact 경로에 맞는 topic create-or-attach 정책을 더 세분화해야 한다.
- `general`의 보존/검색 정책을 더 미세하게 다듬어야 한다.
- retrieval budget을 2차로 더 줄여야 한다. 특히 recent messages, summaries, episodes, raw expansion 쪽을 다시 다이어트해야 한다.
- 채팅 기록이 누적될 때 느려지는 문제를 줄이기 위한 **context compaction / handoff 구조**를 설계해야 한다.
- 새 채팅으로 넘길 때 사용할 자동 handoff 요약 흐름을 정리해야 한다.
- `trusted_search`는 여전히 stub 상태이므로, 향후 실제 구현 필요 여부와 우선순위를 다시 평가해야 한다.

---

## 중간 우선순위

- `PROFILE_SELECTION_QUERY` 같은 selection 목적 함수의 장기 유지 여부를 검토해야 한다. 현재는 허용했지만 장기적으로 더 나은 구조가 있을 수 있다.
- topic 생성 품질이 부족할 때만 embedding 모델 상향을 검토한다. 지금은 `multilingual-e5-small` 유지가 기본이다.
- memory DB 오염 레코드의 실제 상태를 다시 확인해야 한다. 초기화/삭제 이후 문서와 실제 상태가 달라졌을 가능성이 있다.
- uploaded profile evidence가 비어 있었던 원인을 현재 구조 기준으로 다시 확인해야 한다.
- profile evidence가 너무 쉽게 `candidate_count=0`이 되는지 재점검해야 한다.
- correction policy 2차 고도화는 이후 구조가 더 안정된 뒤 진행한다.
- topic 수준 merge / split / rebuild까지 가는 correction 재구성 확장은 이후 단계에서 설계한다.

---

## 코드 상태 점검 필요 항목

- `profile_attachment_ingest_service.py`의 follow-up / answer / extract 흐름 전체를 다시 점검해서, 남은 문자열 분기 / 구버전 호출 / 누락 메서드 참조가 없는지 확인해야 한다.
- `app/api.py`의 텍스트 첨부 / ZIP / 일반 채팅 분기 구조를 다시 점검해서, 하드코딩 트리거나 불필요한 경로 분기가 남아 있지 않은지 확인해야 한다.
- `project_analysis/services/project_profile_evidence_service.py`와 `profile_analysis/services/project_profile_evidence_service.py`의 역할 중복 여부를 확정해야 한다.
- `reply_guard.py`, `response_builder.py`, `system_prompt.txt`에서 특정 도메인(예: 블로그/글/화자)에 묶인 표현이 다시 생기지 않게 해야 한다.
- `passage_selection_service.py`는 이제 임베딩 기반으로 바뀌었지만, 후속 수정에서 휴리스틱이 다시 섞이지 않게 주의해야 한다.

---

## 보류 / 결정 완료 메모

- `passage_selection_service.py`의 **기존 휴리스틱은 보조로서도 유지하지 않음**
- recent source 정책은 **최근 3개 유지 + 사용자 발화 4턴 미사용 시 후보 제외**
- recent source는 질문마다 자동 검사하지 않고, **필요할 때만 lookup**
- 텍스트 첨부 라우팅 fallback은 일단 유지
- `project_id`는 topic으로 대체하지 않고 **출처 축**으로 유지
- 전체 재빌드보다는 **핵심 계층 재구현/재정렬**이 더 적절하다고 판단
- `memory_classification_policy.py`는 upstream에서 이미 모델을 태운다면, **추가 모델 호출 없이 정책층으로만 남기는 방향**으로 간다
- `PROFILE_SELECTION_QUERY` 같은 고정 목적 함수는 현재는 유지 허용

---

## 적용됐거나 1차 반영된 것

- <span style="color:#888">~~기준 작업본을 ZIP이 아니라 현재 작업본 기준으로 이어가는 원칙 정리~~</span>
- <span style="color:#888">~~UI에서 Ollama 모델 선택 가능~~</span>
- <span style="color:#888">~~`/models` API와 `/chat`의 model 전달 경로 연결~~</span>
- <span style="color:#888">~~텍스트 첨부 프로필 요청을 preview-first에서 update-first로 전환~~</span>
- <span style="color:#888">~~`ProfileAttachmentIngestService` 기반 source → evidence → sync → answer 흐름 1차 반영~~</span>
- <span style="color:#888">~~첨부 텍스트 최종 답변을 코드 템플릿이 아니라 모델 생성으로 변경~~</span>
- <span style="color:#888">~~질문 원문 복사 억제를 위한 요청 요약 경로와 answer prompt 보강~~</span>
- <span style="color:#888">~~Ollama `done_reason == length` 감지 추가~~</span>
- <span style="color:#888">~~memory contamination 방어용 필터 1차 추가~~</span>
- <span style="color:#888">~~system prompt를 사용자 하드코딩보다 운영 원칙 중심으로 정리하는 방향 반영~~</span>
- <span style="color:#888">~~prompt 안의 사용자 개인 정보 하드코딩을 줄이고 memory/correction 중심으로 가는 방향 확정~~</span>
- <span style="color:#888">~~project/profile 관련 prompt 외부화 진행~~</span>
- <span style="color:#888">~~troubleshooting 문서화 진행~~</span>
- <span style="color:#888">~~requirements.txt와 README 1차 정리~~</span>
- <span style="color:#888">~~topic 객체화(`topics` 테이블, `topic_id` 중심 구조) 1차 반영~~</span>
- <span style="color:#888">~~active topic 유지 / attach / create 뼈대 반영~~</span>
- <span style="color:#888">~~새 topic 생성 제약 1차 반영~~</span>
- <span style="color:#888">~~`general` 기본 주입 제외 및 90일 TTL 방향 반영~~</span>
- <span style="color:#888">~~confirmed profile의 공격형 승격 방향 1차 반영~~</span>
- <span style="color:#888">~~`project_id`는 제거하지 않고 출처 축으로 유지하기로 결정~~</span>
- <span style="color:#888">~~`ResponseRunner` 공용화 1차 반영~~</span>
- <span style="color:#888">~~`MemoryClassificationPolicy` 공용화 1차 반영~~</span>
- <span style="color:#888">~~`EvidenceExtractionService` 공용화 1차 반영~~</span>
- <span style="color:#888">~~`PassageSelectionService` 공용화 1차 반영~~</span>
- <span style="color:#888">~~`reply_guard.py`의 완성형 한국어 매크로 응답 제거~~</span>
- <span style="color:#888">~~`app/api.py`의 블로그/글/화자/직전 파일 문자열 트리거 제거~~</span>
- <span style="color:#888">~~텍스트 첨부 라우팅을 문자열 규칙에서 모델 판단 기반으로 1차 전환~~</span>
- <span style="color:#888">~~중복된 언어 신호 상수(`FIRST_PERSON_MARKERS` 등)를 공통 파일로 모으는 1차 정리~~</span>
- <span style="color:#888">~~prompt에서 특정 도메인 하드코딩 표현 일부 일반화~~</span>
- <span style="color:#888">~~프롬프트 경량화 1차 반영~~</span>
- <span style="color:#888">~~`profile_attachment_ingest_service.py`의 `_build_extract_messages()` 누락 호출과 관련 런타임 버그 수정~~</span>
- <span style="color:#888">~~`_summarize_user_request()`의 문자열 분기 제거~~</span>
- <span style="color:#888">~~`passage_selection_service.py`를 휴리스틱 없이 임베딩 기반 selection으로 전환~~</span>
- <span style="color:#888">~~`app/api.py`의 `filename: str | None` 타입 경고 수정~~</span>

---

## 나중에 확인할 메모

- `topic 분류는 아직 규칙 기반`이라는 과거 메모는 현재 코드 상태와 다를 수 있으므로, 이후 문서 정리 시 현재 코드 기준으로 다시 검증해야 한다.
- `profile evidence는 아직 evidence/candidate 계층까지만 반영` 같은 과거 메모도, 지금 코드에선 일부 조건부 승격 로직이 이미 들어가 있으므로 최신 상태 기준으로 다시 검토해야 한다.
