# MK5

## 개요
MK5는 기존의 “프로필 문장 저장 + 프롬프트 주입” 중심 구조에서 벗어나,
**입력을 의미 단위로 분해하고, 하나의 세계 그래프에 누적하며, 그 그래프의 국부 활성화 위에서 사고를 전개한 뒤, 마지막에만 언어로 표현하는 인지형 대화 시스템**을 목표로 한다.

즉 MK5의 핵심은 “더 좋은 답변 생성기”가 아니라,
**인지 → 사고 → 설명형 결론 → 얇은 행동형 레이어 → 언어화**를 분리한 구조를 실제로 구현하는 데 있다.

---

## 장기적인 의미
이 프로젝트는 단순히 기존 LLM 위에 메모리를 덧씌우는 실험이 아니다. 장기적으로는 다음 문제의식을 다룬다.

1. **정보를 받는 것과 이해하는 것을 분리한다.**
   - 입력을 바로 답변으로 연결하지 않는다.
   - 먼저 의미블록과 관계로 해석하고, 그 결과를 세계 그래프에 반영한다.

2. **지식을 문장 모음이 아니라 구조로 취급한다.**
   - 노드는 문장 자체가 아니라, 반복 입력을 거치며 체감되고 안정화된 개념이다.
   - 엣지는 단순 연결이 아니라 관계, 차이, 조건, 충돌 압력을 담는다.

3. **세계 그래프는 하나다.**
   - 사용자 발화, 모델 발화, 검색 결과를 서로 다른 “층”으로 분리해 별도 저장하지 않는다.
   - 대신 하나의 세계 그래프 안에 넣되, 출처와 주장 종류에 따라 초기 trust와 증감률을 다르게 둔다.

4. **설명 가능한 구조를 본체로 둔다.**
   - 행동형 지시는 설명형 conclusion으로부터 파생 가능하다.
   - 반대로, 설명 없는 행동형 결론만으로는 원래 사고 구조를 복원하기 어렵다.
   - 그래서 MK5의 본체는 설명형이고, 행동형은 얇은 파생 출력이다.

5. **외부 정보도 세계 그래프에 영향을 줄 수 있다.**
   - 검색 결과도, 모델 답변도, 사용자 발화도 그래프에 들어갈 수 있다.
   - 다만 source_type과 claim_domain에 따라 낮은 trust에서 시작하고, 반복성과 교차 일치로 강화된다.

---

## 핵심 철학

### 1. 본체는 구조다
MK5에서 본질은 “문장 생성”이 아니라 “구조 형성”이다.
- 원문은 provenance로 남는다.
- 영구 그래프에는 재사용 가능한 의미블록이 저장된다.
- 응답은 이 구조의 결과를 언어로 치환한 표면이다.

### 2. 기본은 구조 보존이다
새로운 구조가 들어오더라도, 기존 연결을 즉시 부수지 않는다.
- 기본은 기존 구조를 유지한다.
- 다만, 기존 구조를 깨야만 설명 가능한 반례가 반복적으로 누적되면 trust를 낮춘다.
- trust가 임계점 밑으로 내려가면 revision candidate가 되고, 필요하면 구조를 교체한다.

### 3. 설명형 conclusion이 본체다
MK5의 사고 결과는 설명형 `CoreConclusion`으로 남는다.
- `activated_concepts`는 node id 참조 목록이다.
- `key_relations`는 edge id 참조 목록이다.
- `detected_conflicts`, `trust_changes`, `revision_decisions`를 통해 구조적 판단이 남는다.

### 4. 행동형은 얇은 파생 레이어다
행동형 계획이나 “다음으로 무엇을 할지”는 설명형 conclusion 위에 얹힌다.
현재 구현에서는 `DerivedActionLayer`가 이 역할을 맡고 있다.

### 5. 언어화는 사고가 아니다
언어화 모델은 세계를 이해하는 주체가 아니다.
이미 만들어진 conclusion과 action layer를 자연어로 다듬어 표현하는 역할만 맡는다.
현재는:
- `mk5-graph-core` → template verbalizer
- 선택된 OLLAMA 모델 → `OllamaVerbalizer`
로 연결된다.

### 6. 세계 그래프는 하나지만 확실성은 차등적이다
MK5는 별도의 evidence layer를 두기보다, 같은 세계 그래프 안에 모두 넣는다.
대신 다음이 다르다.
- 초기 trust
- support 시 trust 상승률
- conflict 시 trust 하락률

즉 **존재는 허용하되, 확실성은 출처와 반복성으로 조절**한다.

---

## 현재 구현 상태

### 구현 완료
- SQLite 스키마와 repository 계층
- Graph ingest
- source-aware trust policy
- 국부 활성화(`ThoughtView`)
- `PatternDetector` 기반 SubgraphPattern 감지 및 활성화
- `ConflictResolutionPolicy` 기반 패턴 충돌 해결
- `ActivationEngine`에서 ThoughtView 생성 후 자동 패턴 활성화
- `ThoughtView.activated_patterns` 지원
- 충돌 감지 / trust 하락 / revision 검토
- 설명형 core conclusion 생성
- 얇은 행동형 레이어(`DerivedActionLayer`)
- template verbalizer
- 선택 모델 OLLAMA verbalizer 연결
- 검색 sidecar (낮은 trust의 검색 결과 그래프 반영)
- assistant 답변 자체의 그래프 반영
- chat end-to-end pipeline
- 최소 Flask API 셸
- 기본 chat UI
- integration tests

### 아직 미완료
- Flask 실서버 기동 검증
- `requirements.txt`
- debug UI 패널 최종 정리
- meaning block 정교화
- revision 고도화
- 검색 결과의 다중 출처 corroboration
- 출처/주장 종류별 신뢰도 정책의 세밀화

---

## 현재 주요 흐름
1. 사용자 입력 수신
2. `GraphIngestService`가 user source로 chat_message / graph_event / node / edge / pointer 기록
3. `ActivationEngine`이 현재 입력 기준 seed block / seed node / local graph 생성
4. `PatternDetector`가 `ThoughtView`를 분석해 SubgraphPattern을 감지하고 활성화한다
5. `ThoughtEngine`이 contradiction / trust / revision 검토 수행
5. `ConclusionBuilder`가 설명형 `CoreConclusion` 생성
6. 필요 시 `SearchSidecar`가 외부 검색 결과를 가져옴
7. 검색 결과를 `source_type="search"`, 낮은 trust로 같은 세계 그래프에 반영
8. 다시 activation / thinking 수행
9. `DerivedActionLayer` 생성
10. 선택 모델 또는 템플릿 verbalizer가 최종 사용자 응답 생성
11. assistant 답변도 `source_type="assistant"`, 낮은 trust로 같은 세계 그래프에 반영

---

## 신뢰도 정책 개요

### source_type 예시
- `user`
- `assistant`
- `search`
- `file`

### claim_domain 예시
- `user_state_or_preference`
- `general_claim`
- `graph_interpretation`
- `generated_answer`
- `world_fact`

### 기본 원칙
- 사용자의 자기 상태/선호 진술은 비교적 높은 trust에서 시작
- 일반 사용자 발화는 중간 trust에서 시작
- 검색 결과는 낮거나 중간 trust에서 시작
- 모델 발화는 더 낮은 trust에서 시작
- 같은 내용이 반복되거나, 다른 source와 교차 일치하면 trust 상승
- 충돌과 반례가 누적되면 trust 하락 및 revision 후보화

---

## 실행
### Windows
```bash
py -m venv .venv
.venv\Scripts\activate
pip install flask
python run.py
```

브라우저:
```text
http://127.0.0.1:5000
```

### 테스트
```bash
python tests/unit/test_sqlite_repository_smoke.py
python tests/integration/test_chat_graph_pipeline.py
python tests/integration/test_activation_engine_pipeline.py
python tests/integration/test_thinking_revision_pipeline.py
python tests/integration/test_end_to_end_chat_pipeline.py
python tests/test_activation_engine_integration.py
```

---

## 다음 우선 작업
1. `requirements.txt` 추가
2. debug UI 패널 최종 정리
3. 검색 결과 다중 출처 corroboration
4. source_type × claim_domain 신뢰도 정책 세밀화
5. meaning block / contradiction / revision 정교화

---

## 주의
- 현재 기준으로 `project/profile/chat`을 별도 도메인으로 나누지 않는다.
- 모든 입력은 기본적으로 chat 흐름으로 들어오고, project나 profile은 그 그래프 안에서 해석되는 구조다.
- zip 업로드는 sync용일 뿐, 기준본은 항상 현재 로컬 작업본이다.
