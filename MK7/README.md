# MK7

MK7 is the next Machi architecture focused on:

- a persistent world graph
- per-user long-term memory
- one LLM as the dialogue agent
- tool-based graph lookup and web search

Unlike MK6_1, MK7 does not treat the graph itself as the main reasoning engine.
The LLM remains the planner and responder, while the graph acts as durable memory
and retrieval infrastructure.

## Direction

- Keep graph storage and graph accumulation.
- Remove the heavy think loop as the default response path.
- Let the LLM decide when to:
  - search the graph
  - inspect neighbors
  - read user memory
  - search the web
  - store new facts

## Core ideas

### 1. Persistent user anchors

Each user has one durable speaker anchor:

- `user_anchor::<user_id>`

Shared anchors:

- `assistant_anchor::global`
- `search_anchor::global`

This means memory is accumulated across sessions under the same user identity.

### 2. Graph as memory, not as the thinker

The world graph stores:

- concepts
- relations
- user utterance traces
- search-derived facts
- corrections and conflicts

The graph is queried through tools instead of a standalone thought engine.

### 3. Search as a tool call

MK7 is designed around the same general pattern used by modern agent systems:

- the LLM decides when search is needed
- the search tool returns structured results
- the graph optionally stores useful results for future turns

## Planned modules

- `app/`: server and request pipeline
- `core/agent/`: orchestration for LLM + tools
- `core/graph/`: graph schema, anchors, repository, memory services
- `tools/`: LLM adapter, web search adapter, graph tool surface
- `docs/`: architecture notes
- `tests/`: early unit tests for stable building blocks

## Current status

MK7 now includes:

- a SQLite-backed graph repository at `MK7/data/memory.db`
- persistent `user_anchor::<user_id>` nodes
- per-turn utterance persistence under the user anchor
- token/concept graphization for user utterances and search text
- a tool-using chat loop for graph search, internet search, file access, and terminal access

The next steps are:

1. persist richer fact nodes and relation writes beyond raw utterance storage
2. save useful search-derived facts back into the graph
3. add correction/conflict persistence rules
4. improve workspace editing from plain file writes into patch-oriented edits
