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
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "gemma4:e4b").strip()
OLLAMA_IMAGE_MODEL_NAME = os.getenv("MK5_OLLAMA_IMAGE_MODEL_NAME", "gemma4:12b").strip()
OLLAMA_IMAGE_FALLBACK_MODEL_NAME = os.getenv("MK5_OLLAMA_IMAGE_FALLBACK_MODEL_NAME", "gemma4:12b").strip()
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "768"))
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "false").strip().lower() in {"1", "true", "yes", "on"}

AGENT_MAX_IDENTICAL_TOOL_CALLS = int(os.getenv("MK5_AGENT_MAX_IDENTICAL_TOOL_CALLS", "3"))
AGENT_MAX_PARSE_FAILURES = int(os.getenv("MK5_AGENT_MAX_PARSE_FAILURES", "3"))
AGENT_MAX_UNKNOWN_TOOL_GUARDS = int(os.getenv("MK5_AGENT_MAX_UNKNOWN_TOOL_GUARDS", "2"))
MEMORY_SUMMARY_LIMIT = int(os.getenv("MK5_MEMORY_SUMMARY_LIMIT", "10"))
RECENT_MESSAGE_LIMIT = int(os.getenv("MK5_RECENT_MESSAGE_LIMIT", "10"))
AUTO_ATTACHMENT_TOOL_LIMIT = int(os.getenv("MK5_AUTO_ATTACHMENT_TOOL_LIMIT", "3"))
FILE_TEXT_NODE_KEEP_RATIO = float(os.getenv("MK5_FILE_TEXT_NODE_KEEP_RATIO", "0.7"))
FILE_TEXT_NODE_MAX_ITEMS = int(os.getenv("MK5_FILE_TEXT_NODE_MAX_ITEMS", "24"))
FILE_TEXT_ACTIVATION_MAX_CHARS = int(os.getenv("MK5_FILE_TEXT_ACTIVATION_MAX_CHARS", "8000"))
TERMINAL_TIMEOUT_SECONDS = float(os.getenv("MK5_TERMINAL_TIMEOUT_SECONDS", "20"))
WEB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("MK5_WEB_SEARCH_TIMEOUT_SECONDS", "12"))
AGENT_DEBUG_LOG = os.getenv("MK5_AGENT_DEBUG_LOG", "true").strip().lower() in {"1", "true", "yes", "on"}
MODEL_FAILURE_PREVIEW_CHARS = int(os.getenv("MK5_MODEL_FAILURE_PREVIEW_CHARS", "2000"))

OLLAMA_EXCLUDED_MODELS: frozenset[str] = frozenset(
    name.strip()
    for name in os.getenv("OLLAMA_EXCLUDED_MODELS", "embeddinggemma:latest,nomic-embed-text").split(",")
    if name.strip()
)
