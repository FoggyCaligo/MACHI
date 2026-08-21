# Turn-scoped memory cycle

MK4의 정상 대화 턴은 다음 순서를 따른다.

```text
0. raw utterance record
   - 현재 USER 발화의 utterance node와 spoke edge는 즉시 기록
   - 현재 발화의 concept graphization은 아직 하지 않음

1. recall_memory
   - 매 턴 최소 1회 필수
   - 기본 반환은 focus + immediate relations의 1-hop graph
   - 현재 턴에서 새로 파생될 concept는 아직 recall 공간에 없음
   - 필요하면 추가 recall 가능

2. tool review + answer draft
   - memory mutation은 아직 노출하지 않음
   - 일반 tool들을 노출한 상태에서 모델이 필요성을 판단
   - 필요한 tool이 있으면 사용하고 이 단계를 반복
   - tool이 필요 없으면 별도 skip 호출 없이 곧바로 answer draft 생성
   - tool이 노출된 상태에서 final answer를 선택한 것 자체가 no-tool 결정

3. scoped memory commit
   - write_memory 또는 revise_memory를 최소 1회 성공
   - 필요하면 여러 mutation을 연쇄적으로 수행 가능
   - 완료 후 finish_memory_commit

4. current utterance graphization
   - memory commit이 성공한 뒤에만 현재 USER 발화를 concept graph로 확장

5. answer release
   - memory commit이 성공한 경우에만 이미 고정된 draft를 정상 최종 답변으로 전달
   - 기존 completion/evidence guard가 이후 draft를 거부하면 그 실패를 숨기지 않고 다음 실행 라운드로 돌아감
```

## Why graphization is deferred

현재 USER 발화의 raw utterance record 자체는 대화 기록이므로 즉시 남긴다. 하지만 그 발화에서 파생되는 concept node와 `user_mentions_concept`, `user_references_concept`, `user_adjacent_concept` edge는 mandatory recall이 끝날 때까지 만들지 않는다.

이렇게 하면 첫 recall이 방금 입력된 문장의 concept를 다시 과거 기억처럼 읽는 self-recall 오염을 막을 수 있다. 기존의 과거 utterance/concept graph는 그대로 recall 대상이며, 현재 턴의 concept graph만 memory commit 성공 뒤에 반영된다.

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

필수 recall, graph mutation, memory commit 중 하나라도 완료되지 않으면 정상 답변으로 숨기지 않는다. 특히 answer draft 생성 후 memory commit이 실패하면 draft를 사용자에게 성공 응답으로 반환하지 않는다. 현재 USER 발화의 concept graphization도 memory commit 성공 전에는 수행하지 않는다.
