from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = Path(os.getenv("MK5_WORKSPACE_ROOT", str(BASE_DIR.parent))).resolve()
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("MK5_DB_PATH", str(DATA_DIR / "memory.db"))).resolve()
SENTENCE_BREAKER_DB_PATH = Path(
    os.getenv("MK5_SENTENCE_BREAKER_DB_PATH", str(DATA_DIR / "sentence_breaker.db"))
).resolve()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "gemma3:4b").strip()
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "768"))
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "false").strip().lower() in {"1", "true", "yes", "on"}

AGENT_MAX_TOOL_ROUNDS = int(os.getenv("MK5_AGENT_MAX_TOOL_ROUNDS", "10"))
TERMINAL_TIMEOUT_SECONDS = float(os.getenv("MK5_TERMINAL_TIMEOUT_SECONDS", "20"))
WEB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("MK5_WEB_SEARCH_TIMEOUT_SECONDS", "12"))
AGENT_DEBUG_LOG = os.getenv("MK5_AGENT_DEBUG_LOG", "true").strip().lower() in {"1", "true", "yes", "on"}

OLLAMA_EXCLUDED_MODELS: frozenset[str] = frozenset(
    name.strip()
    for name in os.getenv("OLLAMA_EXCLUDED_MODELS", "embeddinggemma:latest,nomic-embed-text").split(",")
    if name.strip()
)
