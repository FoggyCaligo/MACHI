# Think / Update 루프

작성: 2026-04-21  
상태: Update 구현 완료 → `core/thinking/thought_engine.py`  
      Think 설계 완료, 구현 예정

---

## 개요

MK6의 사고 과정은 두 단계로 분리된다.

```
Update 루프  →  Think 루프
(그래프 갱신)    (결론 형성)
```

두 루프는 역할이 다르다.

| | Update | Think |
|---|---|---|
| 목적 | 세계그래프를 최신 상태로 갱신 | 목표에 닿는 결론 구조를 형성 |
| 입력 | TranslatedGraph (EmptySlot 포함) | 갱신된 TempThoughtGraph |
| 출력 | 커밋된 WorldGraph + 채워진 TempThoughtGraph | ConclusionView |
| WorldGraph 수정 | 있음 (ingest, 엣지 추가, 분화) | 없음 (읽기 전용) |
| 검색 | 있음 (EmptySlot 처리) | 없음 |

---

## Update 루프 (현재 `think` 구현)

**역할:** 빈 곳을 채우고, 세계그래프를 갱신한다.

```
Update 루프
  │
  ├─ EmptySlot 처리
  │    - tg.has_empty_slots() → True이면 검색 트리거
  │    - user_input 원문으로 1회 검색 → _ingest_slot(hint, search_text)
  │    - ingest 완료 노드 간 co_occurrence 엣지 생성
  │
  ├─ ConceptDifferentiation
  │    - 임시 사고 그래프 내 유사 노드 쌍 탐지
  │    - 공통 의미 노드 생성 (abstract, 레이블 없음)
  │    - 필요 시 WorldGraph 약한 커밋
  │
  ├─ 수렴 판단
  │    - 구조 변화 없음 → 루프 종료
  │    - THINK_MAX_LOOPS 상한 안전장치
  │
  └─ WorldGraph 강한 커밋 (새로 추가된 노드/엣지)
```

Update 루프의 수렴 조건: **구조적 변화 없음** (노드/엣지 증감 없음).

---

## Think 루프 (신설 예정)

**역할:** 세계그래프를 기준으로, 목표에 가장 유사하게 닿기 위해 현재 활성화된 국소그래프들을 이리저리 조작하며 결론을 만들어낸다.

WorldGraph는 수정하지 않는다. 오직 TempThoughtGraph 안에서만 조작이 일어난다.

### 핵심 아이디어

```
"불을 끄려면?" 입력에서:

Update 후 TempThoughtGraph:
  불 (ConceptPointer)
  끄다 (ConceptPointer or ingest)
  → 두 노드가 목표 노드에 임시 연결됨

Think 루프가 할 일:
  불 → [방법] → 물 (WorldGraph에 이미 있는 경로)
  불 → [대처] → 소화기
  불 → [담당] → 소방수
  → 이 경로들이 목표(질문에 답하는 구조)에 더 유사하게 닿는다
  → ConclusionView에 물, 소화기, 소방수가 포함됨

단순 재진술 ("불, 끄다")이 아니라
목표 달성에 기여하는 관련 개념들이 결론에 포함된다.
```

### 동작 원리 (설계안)

```
Think 루프
  │
  ① 목표 벡터 산출
  │    - Goal 노드와 현재 입력 노드들 간의 관계 구조 파악
  │    - "이 질문이 무엇을 향하는가"를 그래프 구조로 표현
  │
  ② 관련 노드 탐색 (spreading activation)
  │    - TempThoughtGraph에서 입력 노드들로부터 N-hop 탐색
  │    - WorldGraph에서 불러온 이웃 구조를 TempThoughtGraph에 추가 로드
  │    - 목표 방향과 유사한 노드 경로에 활성화 강도 부여
  │
  ③ 결론 후보 선별
  │    - 활성화 강도가 높은 노드를 결론 후보로 수집
  │    - 단순 재진술(입력 토큰과 동일한 노드)보다
  │      목표 방향으로 연결된 새로운 노드를 우선
  │
  ④ 수렴 판단
  │    - 더 이상 목표 방향으로 활성화할 새 경로가 없으면 종료
  │    - MAX_THINK_LOOPS 상한 안전장치
  │
  └─ ConclusionView 구성
       - key_hashes: importance 상위 20% + 목표 방향 활성 노드
       - ref_hashes: importance 하위 20% + 보조 경로 노드
       - nodes/edges: 결론 형성에 기여한 국소그래프
```

### Update와의 순서

```
LangToGraph
  │
  ▼
TempThoughtGraph 구성
  │
  ▼
Update 루프  ← EmptySlot 채우기, WorldGraph 갱신
  │
  ▼
Think 루프   ← 목표 방향으로 결론 형성 (WorldGraph 수정 없음)
  │
  ▼
ConclusionView → GraphToLang
```

Update가 먼저 끝나야 Think가 완전한 그래프 위에서 동작할 수 있다.  
Update가 "재료 준비"라면 Think는 "요리"다.

---

## ConceptMerge (신설 예정)

분화(ConceptDifferentiation)의 대칭 축이다.

현재 Update 루프에는 **분화만** 있다.  
분화가 "뭉친 개념을 분리"한다면, 병합은 "중복/동의/표현 차이 개념을 통합"한다.

```
분화: 유사 노드 쌍 → 공통 상위 노드 추출 + 차이 분리
병합: 동의어/표현 변형 노드 쌍 → 단일 노드로 통합 + words 테이블 재연결
```

**ConceptMerge 동작 조건:**
- 두 노드의 임베딩 유사도가 매우 높고 (분화 threshold보다 높은 별도 기준)
- 이웃 구조가 거의 동일하며
- 어느 쪽도 abstract 노드가 아닌 경우

**ConceptMerge가 없으면:**
- "글록" / "Glock" / "glock" 이 각각 다른 노드로 남음
- 같은 개념의 표현 변형이 그래프를 파편화함
- 그래프가 성숙할수록 중복 노드가 누적됨

ConceptMerge는 Update 루프 내에서 ConceptDifferentiation과 함께 실행된다.  
두 축이 함께 있어야 의미 그래프가 안정화된다.

---

## 현재 구현 상태

| 컴포넌트 | 상태 | 위치 |
|---|---|---|
| Update 루프 | ✅ 구현 완료 | `core/thinking/thought_engine.py` (`think()`) |
| ConceptDifferentiation | ✅ 구현 완료 | `core/thinking/concept_differentiation.py` |
| Think 루프 | 🔲 설계 완료, 구현 예정 | - |
| ConceptMerge | 🔲 설계 예정 | - |

현재 `ThoughtEngine.think()`는 사실상 Update 루프다.  
향후 `think()`를 `update()`로 rename하고, 그 뒤에 `think()`를 신설한다.
