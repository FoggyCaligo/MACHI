# MK6 CorrectionGraph 정책

작성: 2026-05-18  
상태: skeleton 정책 v1  
범위: 사용자 정정 발화와 직전 assistant assertion 사이의 구조적 충돌 처리

---

## 1. 핵심 결정

사용자가 직전 응답을 정정하는 상황은 일반 질의와 다르게 처리한다.

```text
사용자 발화
→ 직전 assistant assertion과 conflict
→ user correction edge 생성
→ 이전 잘못된 귀속 edge trust 하향
→ 정정된 구조를 ConclusionGraph로 구성
```

이 구조는 문자열 패턴으로 `아냐`, `틀렸어`, `그게 아니야`를 탐지하는 방식으로 구현하지 않는다.

CorrectionGraph는 다음 두 그래프 상태의 관계로 만든다.

```text
current input graph
previous assistant state graph
```

---

## 2. 현재 구현 범위

현재 구현은 완성된 correction engine이 아니라 1차 skeleton이다.

포함:

```text
- Pipeline이 세션별 직전 assistant state를 저장한다.
- 다음 턴 ThoughtEngine에 PreviousAssistantState를 전달한다.
- 현재 입력 graph와 직전 assistant graph가 같은 국소 사고공간에 들어오면 correction candidate를 만든다.
- current node → previous assertion node 방향의 temporary conflict edge를 만든다.
- 직전 assistant selected graph의 edge에 correction pressure를 임시로 반영한다.
- CorrectionGraph를 selected_graphs의 최상단에 삽입한다.
- GraphToLang이 CorrectionGraph를 일반 answer graph와 분리해서 프롬프트에 제공한다.
```

제외:

```text
- correction 여부의 최종 확정
- 영구 WorldGraph commit
- 특정 과거 edge의 실제 삭제
- 사용자 정정의 신뢰도 누적 정책
- 동일 이름/동명이인 등 구체 관계의 정교한 구조화
```

---

## 3. PreviousAssistantState

직전 assistant 응답은 텍스트로만 보관하지 않는다.

```python
PreviousAssistantState:
  key_hashes
  ref_hashes
  selected_graphs
  edge_ids
```

이는 직전 assistant가 어떤 노드와 edge를 중심으로 답했는지 추적하기 위한 압축 상태다.

---

## 4. CorrectionGraph 생성 조건

현재 구현은 다음 조건을 만족할 때 correction candidate를 만든다.

```text
1. previous assistant state가 있다.
2. 현재 입력 graph에 노드가 있다.
3. 직전 assistant graph에 노드가 있다.
4. current graph와 previous graph가 직접 shared node를 갖거나,
   non-temporary edge로 인접한다.
5. 현재 입력이 직전 상태의 단순 반복이 아니다.
```

중요한 점:

- 문자열 기반 정정 탐지는 하지 않는다.
- 같은 국소 그래프 안에서 새 구조가 들어왔을 때 correction 후보로 본다.
- 현재는 conservative skeleton이므로, 완벽한 correction 판정이 아니라 후보 구조를 만든다.

---

## 5. Conflict edge

CorrectionGraph는 현재 사용자 입력 쪽 노드에서 직전 assistant assertion 쪽 노드로 conflict edge를 만든다.

```text
current_user_node
  →[conflict, user_correction]
previous_assistant_node
```

이 edge는 다음 속성을 가진다.

```text
edge_family="relation"
connect_type="conflict"
provenance_source="user_policy"
proposed_connect_type="user_correction"
is_temporary=True
```

즉, 이 edge는 아직 WorldGraph에 직접 commit되는 정정 사실이 아니다.  
현재 턴에서 GraphToLang과 trace가 볼 수 있는 correction candidate다.

---

## 6. Correction pressure

CorrectionGraph가 만들어지면 직전 assistant selected graph에 포함된 edge에 correction pressure를 약하게 반영한다.

```text
conflict_count += 1
contradiction_pressure += 0.4
trust_score *= 0.75
```

현재 이 조정은 TempThoughtGraph 내부에서만 수행한다.

WorldGraph 영구 반영은 아직 하지 않는다.

---

## 7. GraphToLang 계약

CorrectionGraph가 제공되면 GraphToLang은 다음 방향으로 응답해야 한다.

```text
1. 직전 응답의 일부가 사용자 입력과 충돌할 수 있음을 우선 인정한다.
2. 정정 가능성을 무시하지 않는다.
3. 이전 답변을 반복하거나 방어하지 않는다.
4. 현재 사용자 입력을 기준으로 잘못된 귀속/연결을 분리한다.
5. 확실하지 않은 부분은 모른다고 말한다.
```

예시:

```text
사용자: 엄...아냐. 그 사람들은 동명이인이야.

바람직한 응답:
  맞아. 내가 이전에 같은 이름의 다른 사람 정보를 너에게 잘못 연결했어.
  그 정보는 네 정보로 확정하면 안 되고, 동명이인으로 분리해서 봐야 해.
```

---

## 8. 한계와 TODO

현재 skeleton의 한계:

```text
- correction 여부를 충분히 엄밀하게 확정하지 않는다.
- 단순 관련 발화와 실제 정정 발화를 완전히 구분하지 못할 수 있다.
- WorldGraph edge trust를 영구 갱신하지 않는다.
- SearchResult/source node가 분리되지 않아 잘못된 외부 정보의 출처 추적이 약하다.
```

TODO:

```text
1. assistant assertion graph를 더 명확히 저장한다.
2. user correction graph를 WorldGraph update request로 분리한다.
3. 잘못된 귀속 edge의 trust를 UpdateEngine을 통해 영구 하향한다.
4. 동명이인/동일표면형-다른개념 분리 구조를 word-meaning link와 연결한다.
5. evidence/source node 분리 후, 잘못된 검색 결과와 사용자 self-claim을 구조적으로 분리한다.
6. CorrectionGraph가 생성된 턴에서는 검색 결과보다 사용자 correction edge를 우선한다.
```

---

## 9. 정책 v1

```text
1. Correction은 문자열 패턴이 아니라 current graph와 previous assistant graph의 구조적 충돌로 본다.

2. CorrectionGraph는 graph_kind="correction"인 ConclusionGraph다.

3. CorrectionGraph는 current input node와 previous assistant node 사이의 conflict edge를 포함한다.

4. conflict edge는 초기 skeleton에서는 temporary edge다.

5. correction pressure는 TempThoughtGraph 안에서만 반영한다.

6. GraphToLang은 CorrectionGraph가 있으면 직전 응답 방어보다 정정 인정 방향을 우선한다.

7. WorldGraph 영구 수정은 후속 UpdateEngine 정책으로 분리한다.
```
