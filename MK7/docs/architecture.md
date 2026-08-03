# MK7 Architecture Draft

## Goal

Build a graph-backed long-term memory agent that uses:

- one dialogue LLM
- graph query tools
- optional web search tools

The graph should persist user conversation history and important facts without
requiring a dedicated internal thought engine.

## High-level flow

1. Receive `user_id`, `session_id`, `message`.
2. Ensure the persistent `user_anchor::<user_id>` exists.
3. Record the raw utterance under that user anchor.
4. Load a small user memory summary from graph neighbors.
5. Let the LLM answer using:
   - current message
   - graph memory summary
   - future tool calls for graph and web search
6. Persist useful new facts or search outcomes back into the graph.

## What remains from MK6_1 in spirit

- world graph as a durable memory substrate
- identity anchoring
- search-aware memory growth
- correction and conflict as first-class graph events

## What changes from MK6_1

- no default thought loop
- no default conclusion graph generation
- no graph_to_lang layer
- no search relation extractor in the main response path

## First implementation milestones

### Milestone 1

- stable user anchor creation
- utterance storage
- graph memory summary readout
- simple chat endpoint

### Milestone 2

- graph query tool contract
- LLM adapter with real model backend
- web search adapter

### Milestone 3

- durable fact extraction and write-back
- correction/conflict persistence
- memory browsing UI
