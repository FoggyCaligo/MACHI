# Turn-scoped memory cycle

MK4의 정상 대화 턴은 다음 순서를 따른다.

```text
1. recall_memory
   - 매 턴 최소 1회 필수
   - 기본 반환은 focus + immediate relations의 1-hop graph
   - 필요하면 추가 recall 가능

2. tool review
   - memory mutation은 아직 노출하지 않음
   - 필요한 일반 tool을 사용
   - 일반 tool이 필요 없으면 skip_tool_use

3. answer draft
   - 기존 실행/검증 guard를 모두 통과한 user-visible 답변을 먼저 고정

4. scoped memory commit
   - write_memory 또는 revise_memory를 최소 1회 성공
   - 필요하면 여러 mutation을 연쇄적으로 수행 가능
   - 완료 후 finish_memory_commit

5. answer commit
   - memory commit이 성공한 경우에만 이미 고정된 draft를 사용자에게 반환
```

## Turn graph scope

기존 graph node는 현재 턴의 `recall_memory`가 실제 반환했거나 같은 memory commit에서 새로 생성한 node만 수정/연결할 수 있다.

새 semantic node는 framework가 현재 USER 발화와 고정된 ASSISTANT 답변을 tokenization해서 만든 `writable_terms`의 `term_id`로만 생성할 수 있다. 모델이 자유 문자열로 새 node label을 발명하지 않는다.

```text
writable_terms
- user:0:0 -> 실제 USER 단어
- user:0:1 -> 실제 USER 단어
- assistant:0:0 -> 실제 ANSWER 단어
...
```

edge의 relation은 turn scope 내부에서는 모델이 자유롭게 정할 수 있다. 새 node끼리의 연쇄 연결도 허용한다. 동일한 source/relation/target edge를 다시 추가하면 repository의 기존 계약에 따라 duplicate row 대신 support_count와 edge weight가 강화된다.

## Failure contract

필수 recall, tool review, graph mutation, memory commit 중 하나라도 완료되지 않으면 정상 답변으로 숨기지 않는다. 특히 answer draft 생성 후 memory commit이 실패하면 draft를 사용자에게 성공 응답으로 반환하지 않는다.
