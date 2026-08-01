# MK6_1

`MK6_1` is a graph-first local reasoning stack built on Ollama and SQLite.
User input is translated into an input graph, expanded through a think/update loop,
optionally augmented with search, committed into the world graph, and finally rendered
to language from separate graph sections.

## Current behavior summary

- `LangToGraph` translates user input into an `InputGraphBundle` / `TranslatedGraph`.
- `ThoughtEngine` builds a `TempThoughtGraph` from:
  - the current input graph
  - local world-graph context
  - active profile / identity context
- Search trigger conditions stay conservative and follow the existing policy.
- Empty-slot search no longer sends the whole sentence as one query.
  - slot-oriented search uses per-slot query text
  - duplicate queries are skipped
  - lightweight stopword / suffix cleanup is applied only to search query text
- Search results are no longer treated as plain snippets only.
  - result text is graphized again through `lang_to_graph()`
  - the produced result graph is bridged into the active local graph
  - committed world-graph policy remains unchanged
- GraphToLang now receives three separate graph sections:
  - `input_graph`
  - `conclusion_graph`
  - `search_graph`
- User correction handling is assertion-structure-based, not string-cue-based.
- Surface forms are kept as separate nodes first.
  - `surface_variant_evidence` accumulates language-neutral alias evidence
  - `concept_merge` can merge later only after enough structural support exists

## Main files

- `run_cli.py`: CLI entrypoint
- `run_server.py`: FastAPI server entrypoint
- `app/server.py`: `/`, `/chat`, `/models`, `/health`
- `app/pipeline.py`: end-to-end pipeline orchestration
- `core/translation/lang_to_graph.py`: input-to-graph translation
- `core/thinking/thought_engine.py`: update loop, search, graph commit
- `core/thinking/claim_graph.py`: user assertion / correction graph logic
- `core/thinking/surface_variant_evidence.py`: alias-evidence accumulation
- `core/thinking/concept_merge.py`: conservative delayed merge
- `core/verbalization/answer_contract_clean.py`: 3-section answer contract
- `tools/ollama_client.py`: Ollama chat / embedding / model listing
- `data/memory.db`: SQLite world graph

## Requirements

- Python 3.12 or newer recommended
- local [Ollama](https://ollama.com/) running
- at least one generation model installed
- at least one embedding model installed

Default assumptions:

- generation model: `gemma3:4b`
- embedding model: `nomic-embed-text`
- Ollama host: `http://localhost:11434`
- DB path: `data/memory.db`

## First-time setup

### 1. Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 2. Start Ollama

```bash
ollama serve
```

If Ollama is already running in the background, you can skip this.

### 3. Pull required models

```bash
ollama pull gemma3:4b
ollama pull nomic-embed-text
```

If you only needed the Gemma command:

```bash
ollama pull gemma3:4b
```

## Run

### CLI

```bash
python run_cli.py
```

Exit with:

- `exit`
- `quit`
- `Ctrl+C`

### Server

```bash
python run_server.py
```

Example:

```bash
python run_server.py --host 127.0.0.1 --port 8000 --reload
```

Default endpoints:

- UI: `http://127.0.0.1:8000/`
- health: `http://127.0.0.1:8000/health`
- models: `http://127.0.0.1:8000/models`

## `/chat` pipeline

1. Translate input into `TranslatedGraph`.
2. Build a temporary local graph from direct input, local context, and active profile context.
3. Run the update/think loop.
4. If search is triggered, search with slot-oriented queries under the existing trigger policy.
5. Graphize search results and bridge them into the active local graph.
6. Commit strong new content into `memory.db` under the existing commit policy.
7. Build the answer contract with separate `input_graph`, `conclusion_graph`, and `search_graph`.
8. Generate the final response through the configured Ollama model.

## Search behavior

### Query generation

Search is no longer driven by the whole raw sentence for empty-slot filling.

- Empty-slot search:
  - choose the most important unresolved slots
  - derive one query per target slot
  - skip duplicate slot queries
- No-slot search:
  - existing trigger policy is preserved
  - the system still avoids unnecessary search when graph evidence is already sufficient

### Search-result graphization

Search results are converted back into graph structure instead of being treated as plain text only.

- title / snippet text can produce new or existing concept nodes
- result-origin edges are marked with search provenance
- result graph content is exposed separately as `search_graph`
- bridge edges connect the result graph with the currently active local graph

### World-graph reflection

Search-result graph content follows the existing world-graph commit policy.

- strong nodes / edges can be committed into `memory.db`
- weak or temporary structures stay conservative
- repeated result evidence can strengthen already-known nodes and edges

## Identity and correction handling

### Identity

User self-reference is not handled through hard-coded names.

- active input concepts
- `ProfileActivationView`
- `identity_surface`
- `profile_reference`

are used together to bind the current speaker structurally.

### Correction

Correction detection does not depend on cue strings such as specific words for "no" or "correction".

It works through assertion replacement:

- extract current user assertions
- compare them against recent assistant assertions
- when the same subject now points to a different object:
  - attach `user_correction_conflict` toward the previous object
  - attach `user_assertion` toward the new object
  - raise contradiction pressure on the previous assertion edge

## Delayed merge policy

`MK6_1` does not force two surface forms into one node immediately.

Instead:

1. each surface form can remain as its own node
2. `surface_variant_evidence` accumulates language-neutral support between likely aliases
3. `concept_merge` merges later only when all of the following are strong enough:
   - embedding similarity
   - shared structural neighborhood
   - repeated / accumulated evidence
   - node stability

This keeps early representation flexible while still allowing later consolidation.

## GraphToLang contract

GraphToLang receives three sections instead of one mixed blob:

- `input_graph`
  - structure directly tied to the current user input
  - speaker=`user`
- `conclusion_graph`
  - structure selected by the reasoning/update loop
  - speaker=`system`
- `search_graph`
  - externally sourced graphized evidence
  - speaker=`external`

Important behavior:

- first-person user claims should stay user-scoped, not assistant-scoped
- `conclusion_graph` has priority when it contains informative structure
- `search_graph` provides supporting evidence
- if `conclusion_graph` is effectively empty, the system can fall back to input/search context

## Environment variables

- `OLLAMA_HOST`
- `OLLAMA_MODEL_NAME`
- `EMBEDDING_MODEL_NAME`
- `MK6_DB_PATH`
- `OLLAMA_TIMEOUT_SECONDS`
- `EMBEDDING_TIMEOUT_SECONDS`

PowerShell example:

```powershell
$env:OLLAMA_MODEL_NAME="gemma3:12b"
$env:EMBEDDING_MODEL_NAME="nomic-embed-text"
python run_server.py
```

## Troubleshooting

### 1. `404 Not Found` for `/api/embeddings`

`tools/ollama_client.py` now tries both:

- `/api/embeddings`
- `/api/embed`

If both fail, common causes are:

1. Ollama is not actually running
2. `OLLAMA_HOST` is wrong
3. the embedding model is not installed

Check with:

```bash
ollama list
curl http://localhost:11434/api/tags
```

### 2. Missing embedding model

Default embedding model:

```bash
ollama pull nomic-embed-text
```

If you want another embedding model:

```powershell
$env:EMBEDDING_MODEL_NAME="your-embedding-model"
python run_server.py
```

### 3. A model exists in Ollama but does not appear in `/models`

Embedding-only models can be excluded from the response model picker.
That behavior comes from the model filtering policy, not from Ollama itself.

## Tests

Examples:

```bash
python -m pytest .\tests\test_ollama_client.py
python -m pytest .\tests\test_search_result_graphization.py
python -m pytest .\tests\test_answer_contract_sections.py
python -m pytest .\tests\test_claim_graph_correction.py
python -m pytest .\tests\test_surface_variant_evidence.py
```

All tests:

```bash
python -m pytest
```

## References

- `docs/architecture/file_structure.md`
- `docs/architecture/graph_schema.md`
- `docs/architecture/lang_to_graph.md`
- `docs/architecture/claim_assertion_graph.md`
- `docs/architecture/concept_merge.md`
