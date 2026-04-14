# MACHI Project Guidelines

## Code Style
- Use underscores in filenames and variables for readability (e.g., `memory_ingress_service.py`)
- Service classes end with `-Service`, stores with `-Store`
- Database IDs are UUID4 strings
- Config variables prefixed by context (e.g., `OLLAMA_*`, `TOPIC_*`)

## Architecture
MACHI is a local personal cognitive partner with an evidence-first memory system. Key components:
- **Request Pipeline**: API → Orchestrator → Agent → Evidence Extraction → Memory Updates
- **Memory Layers**: Topics (semantic clustering), Profiles (user characteristics with history), Corrections (explicit fixes), Episodes (temporal memories)
- **Core Principle**: Memory is updateable; corrections cascade and supersede old profiles

See [README.md](README.md) for detailed architecture and philosophy.

## Build and Test
```bash
# Setup
cd MK4
python -m venv .venv
pip install -r requirements.txt

# Run
python -m uvicorn app.api:app --reload

# Test
python -m unittest tests.test_*
```

Requires Ollama running locally with `qwen2.5:3b` model.

## Conventions
- Prompts loaded from files in `prompts/` directory
- Evidence extraction returns structured JSON, not free text
- Timeouts handled at service level with fallbacks
- No append-only logs; memory updates via corrections
- Profile statuses: general → candidate → confirmed