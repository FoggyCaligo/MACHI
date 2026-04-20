# ConceptDifferentiation

작성: 2026-04-20  
상태: 구현 완료 → `core/thinking/concept_differentiation.py`

---

## 역할

임시 사고 그래프 내에서 유사한 개념 노드 쌍을 탐지하고, 공통 구조를 추출해 상위 개념 노드로 형성한다.  
차이는 분화(differentiation)로 분리한다.

MK1 원설계의 "노드 = 체감된 개념" 철학을 구현하는 핵심 컴포넌트다.

---

## 실행 시점

Think 루프 내 또는 종료 직후.  
임시 사고 그래프 위에서 실행되고, "세계그래프 반영 필요" 판단이 서면 커밋한다.

---

## 유사도 판정 방식

**복합 스코어 (C안) + 적응형 α**

```
score = α × cosine_sim(emb_A, emb_B)
      + (1 - α) × overlap_ratio(neighbors_A, neighbors_B)

overlap_ratio = |neighbors_A ∩ neighbors_B| / |neighbors_A ∪ neighbors_B|
```

**α 결정 기준 — 노드의 이웃 수에 따라 동적으로 조정:**

```
이웃 수 < MIN_NEIGHBORS_THRESHOLD:
  α = 1.0   → 임베딩 유사도만 사용
              (이웃이 적어 overlap 비교가 의미 없는 초기 상태)

이웃 수 ≥ MIN_NEIGHBORS_THRESHOLD:
  α = max(MIN_ALPHA, 1.0 - (neighbor_count / ALPHA_DECAY_RATE))
              (이웃이 쌓일수록 overlap 비중 증가)
```

- `MIN_NEIGHBORS_THRESHOLD`: 기본 3 (설정값으로 조정 가능)
- `MIN_ALPHA`: 기본 0.3 (overlap이 아무리 많아도 임베딩 최소 반영)
- `ALPHA_DECAY_RATE`: 기본 10

**판정:**
- `score ≥ DIFFERENTIATION_THRESHOLD` → 유사 쌍으로 탐지
- `DIFFERENTIATION_THRESHOLD`: 기본 0.80 (설정값으로 조정 가능)

---

## 분화 후보 조건

노드 쌍을 검사하기 전에 다음 조건을 모두 충족한 노드만 후보에 포함한다:

| 조건 | 이유 |
|---|---|
| `is_abstract == False` | 추상 노드는 이미 분화 결과물 → 재분화 시 자기 증폭 |
| `is_active == True` | 비활성 노드 제외 |
| `embedding is not None` | 유사도 계산 불가 노드 제외 |
| `address_hash != goal_hash` | 목표 노드는 분화 대상 아님 |
| `stability_score > COMMIT_STABILITY_WEAK` | 신규 ingest 노드 제외 |

**stability 필터 설명:**  
신규 ingest 노드는 `stability_score = COMMIT_STABILITY_WEAK (0.1)`로 생성된다.  
개념 경계가 아직 정착되지 않은 상태이므로 분화에 참여하면 의미 없는 추상 노드가 대량 생성된다.  
같은 개념이 반복 등장해 stability가 `COMMIT_STABILITY_WEAK`를 초과할 때부터 분화에 참여한다.

---

## 처리 흐름

```
임시 사고 그래프 내 분화 후보 노드 쌍에 대해:
  │
  ▼
① 유사도 판정
   score = α × cosine_sim + (1-α) × overlap_ratio
   score < threshold → 건너뜀

  ▼
② 유사 쌍 확정
   두 노드 A, B가 유사 쌍으로 판정됨

  ▼
③ 공통 의미 노드 생성
   - 두 노드 임베딩의 centroid 계산
   - 새 노드 생성: is_abstract=True, labels=[], embedding=centroid
   - formation_source="differentiation"

  ▼
④ 차이 분리
   - A, B 각각의 고유 이웃 노드를 differential edge로 연결
   - connect_type: proposed_connect_type에 "differentiation" 후보로 기록
     (기존 승격 경로를 통해 나중에 확정)

  ▼
⑤ 세계그래프 반영 판단
   - 새 공통 노드가 충분히 유의미한가? (trust_score 기준)
   - 유의미하면 WorldGraph에 커밋
   - 아니면 임시 사고 그래프에만 유지
```

---

## words 테이블 동기화

graph_schema.md의 동기화 정책을 따른다.

- **Merge**: 두 노드에 연결된 모든 단어 → 병합 노드로 일괄 이전
- **Differentiation**: 기존 단어들을 두 노드에 임베딩 유사도 기반으로 배분  
  (유사도 차이 < threshold → 양쪽 모두에 연결, 중복 허용)

---

## GraphToLang에서 추상 노드 처리

`is_abstract=True` 노드는 GraphToLang 출력에서 **완전히 제외**한다.

- 핵심 키워드, 참고 개념 양쪽 모두 포함하지 않는다.
- 추상 노드가 엔드포인트인 엣지도 근거 연결에서 제외한다.

**이유:** 추상 노드는 분화 과정에서 생성된 내부 구조 노드다. labels가 없고, LLM 컨텍스트에 포함하면 "[A, B의 공통 개념]" 형태의 노이즈만 추가된다. 추상 노드의 의미는 그 자식 노드(A, B)의 관계를 통해 간접적으로 표현되는 것으로 충분하다.

---

## 설정값 요약

| 설정값 | 기본값 | 설명 |
|---|---|---|
| `DIFFERENTIATION_THRESHOLD` | 0.80 | 유사 쌍 판정 임계치 |
| `MIN_NEIGHBORS_THRESHOLD` | 3 | α 조정이 시작되는 최소 이웃 수 |
| `MIN_ALPHA` | 0.3 | overlap 비중이 최대일 때 임베딩 최소 반영 비율 |
| `ALPHA_DECAY_RATE` | 10 | 이웃 수에 따른 α 감소율 |
