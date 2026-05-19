from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MK6_1_DATA_DIR", str(PACKAGE_ROOT / "data")))
DB_PATH = os.getenv("MK6_1_DB_PATH", str(DATA_DIR / "memory.db"))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "gemma3:4b")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "600"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
OLLAMA_EXCLUDED_MODELS = {m.strip() for m in os.getenv("OLLAMA_EXCLUDED_MODELS", "embeddinggemma:latest").split(",") if m.strip()}
LANG_TO_GRAPH_SIMILARITY_THRESHOLD = float(os.getenv("LANG_TO_GRAPH_SIMILARITY_THRESHOLD", "0.75"))
LANG_TO_GRAPH_MAX_EMBEDDING_NODES = int(os.getenv("LANG_TO_GRAPH_MAX_EMBEDDING_NODES", "200"))
TOKEN_IMPORTANCE_NEAR_RATIO = float(os.getenv("TOKEN_IMPORTANCE_NEAR_RATIO", "0.20"))
TOKEN_IMPORTANCE_FAR_RATIO = float(os.getenv("TOKEN_IMPORTANCE_FAR_RATIO", "0.20"))
TOKEN_IMPORTANCE_MIN = int(os.getenv("TOKEN_IMPORTANCE_MIN", "1"))
LOCAL_GRAPH_N_HOP = int(os.getenv("LOCAL_GRAPH_N_HOP", "2"))
LOCAL_GRAPH_TRUST_THRESHOLD = float(os.getenv("LOCAL_GRAPH_TRUST_THRESHOLD", "0.2"))
THINK_MAX_LOOPS = int(os.getenv("THINK_MAX_LOOPS", "3"))
SEARCH_TIMEOUT = float(os.getenv("SEARCH_TIMEOUT", "20"))
COMMIT_TRUST_STRONG = float(os.getenv("COMMIT_TRUST_STRONG", "0.7"))
COMMIT_TRUST_WEAK = float(os.getenv("COMMIT_TRUST_WEAK", "0.15"))
COMMIT_STABILITY_STRONG = float(os.getenv("COMMIT_STABILITY_STRONG", "0.6"))
COMMIT_STABILITY_WEAK = float(os.getenv("COMMIT_STABILITY_WEAK", "0.1"))
