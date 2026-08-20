from __future__ import annotations

import os
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _string_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in raw.split(",")]
    if not isinstance(parsed, list):
        raise ValueError(f"{name} must be a JSON list or comma-separated string")
    return tuple(dict.fromkeys(str(item).strip() for item in parsed if str(item).strip()))


_load_local_env(BASE_DIR / ".env")
WORKSPACE_ROOT = Path(os.getenv("MK4_WORKSPACE_ROOT", str(BASE_DIR.parent))).resolve()
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("MK4_DB_PATH", str(DATA_DIR / "memory.db"))).resolve()
SESSIONS_DB_PATH = Path(os.getenv("MK4_SESSIONS_DB_PATH", str(DATA_DIR / "sessions.db"))).resolve()
SENTENCE_BREAKER_DB_PATH = Path(
    os.getenv("MK4_SENTENCE_BREAKER_DB_PATH", str(DATA_DIR / "sentence_breaker.db"))
).resolve()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
OLLAMA_MODEL_NAME = os.getenv(
    "MK4_OLLAMA_MODEL_NAME",
    os.getenv("OLLAMA_MODEL_NAME", "qwen3.5:9b"),
).strip()
OLLAMA_IMAGE_MODEL_NAME = os.getenv("MK4_OLLAMA_IMAGE_MODEL_NAME", "gemma4:12b").strip()
OLLAMA_IMAGE_FALLBACK_MODEL_NAME = os.getenv("MK4_OLLAMA_IMAGE_FALLBACK_MODEL_NAME", "gemma4:12b").strip()
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "3072"))
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "false").strip().lower() in {"1", "true", "yes", "on"}
SERVER_HOST = os.getenv("MK4_SERVER_HOST", "127.0.0.1").strip()
SERVER_PORT = int(os.getenv("MK4_SERVER_PORT", "8010"))

AGENT_MAX_ROUNDS = int(os.getenv("MK4_AGENT_MAX_ROUNDS", "40"))
AGENT_MAX_IDENTICAL_TOOL_CALLS = int(os.getenv("MK4_AGENT_MAX_IDENTICAL_TOOL_CALLS", "3"))
AGENT_MAX_PARSE_FAILURES = int(os.getenv("MK4_AGENT_MAX_PARSE_FAILURES", "3"))
AGENT_MAX_UNKNOWN_TOOL_GUARDS = int(os.getenv("MK4_AGENT_MAX_UNKNOWN_TOOL_GUARDS", "2"))
MEMORY_SUMMARY_LIMIT = int(os.getenv("MK4_MEMORY_SUMMARY_LIMIT", "5"))
MEMORY_SUMMARY_MIN_SIGNAL = float(os.getenv("MK4_MEMORY_SUMMARY_MIN_SIGNAL", "0.05"))
RECENT_MESSAGE_LIMIT = int(os.getenv("MK4_RECENT_MESSAGE_LIMIT", "10"))
AUTO_ATTACHMENT_TOOL_LIMIT = int(os.getenv("MK4_AUTO_ATTACHMENT_TOOL_LIMIT", "3"))
FILE_TEXT_NODE_KEEP_RATIO = float(os.getenv("MK4_FILE_TEXT_NODE_KEEP_RATIO", "0.7"))
FILE_TEXT_NODE_MAX_ITEMS = int(os.getenv("MK4_FILE_TEXT_NODE_MAX_ITEMS", "24"))
FILE_TEXT_ACTIVATION_MAX_CHARS = int(os.getenv("MK4_FILE_TEXT_ACTIVATION_MAX_CHARS", "8000"))
TERMINAL_TIMEOUT_SECONDS = float(os.getenv("MK4_TERMINAL_TIMEOUT_SECONDS", "20"))
WEB_SEARCH_TIMEOUT_SECONDS = float(os.getenv("MK4_WEB_SEARCH_TIMEOUT_SECONDS", "12"))
AGENT_DEBUG_LOG = os.getenv("MK4_AGENT_DEBUG_LOG", "true").strip().lower() in {"1", "true", "yes", "on"}
SESSION_COOKIE_SECURE = os.getenv("MK4_SESSION_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
SESSION_TTL_HOURS = int(os.getenv("MK4_SESSION_TTL_HOURS", "168"))
MAX_ACTIVE_SESSIONS = int(os.getenv("MK4_MAX_ACTIVE_SESSIONS", "3"))
ALLOWED_LOGIN_IDS = _string_list("MK4_ALLOWED_LOGIN_IDS")
OWNER_LOGIN_ID = os.getenv("MK4_OWNER_LOGIN_ID", "").strip()
OWNER_GRAPH_USER_ID = os.getenv("MK4_OWNER_GRAPH_USER_ID", "account::owner").strip()
MODEL_FAILURE_PREVIEW_CHARS = int(os.getenv("MK4_MODEL_FAILURE_PREVIEW_CHARS", "2000"))

# Local continuous voice mode. Set MK4_VOICE_ENABLED=false to hide the microphone
# UI and hard-disable all voice preparation/inference endpoints. This is useful
# when MK4 is shared with family or demo users and the host should avoid STT/TTS
# model load, download, and inference cost entirely.
VOICE_ENABLED = os.getenv("MK4_VOICE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
VOICE_AUTO_DOWNLOAD = os.getenv("MK4_VOICE_AUTO_DOWNLOAD", "true").strip().lower() in {"1", "true", "yes", "on"}
VOICE_MODEL_DIR = Path(
    os.getenv("MK4_VOICE_MODEL_DIR", str(DATA_DIR / "voice_models"))
).expanduser().resolve()

# STT: multilingual faster-whisper small balances Korean accuracy, CPU latency and
# memory. A local CTranslate2 directory can be supplied for pre-provisioned use.
VOICE_STT_MODEL = os.getenv("MK4_STT_MODEL", "small").strip() or "small"
VOICE_STT_DEVICE = os.getenv("MK4_STT_DEVICE", "cpu").strip() or "cpu"
VOICE_STT_COMPUTE_TYPE = os.getenv("MK4_STT_COMPUTE_TYPE", "int8").strip() or "int8"
VOICE_STT_LANGUAGE = os.getenv("MK4_STT_LANGUAGE", "ko").strip()
VOICE_STT_BEAM_SIZE = int(os.getenv("MK4_STT_BEAM_SIZE", "1"))
VOICE_STT_CPU_THREADS = int(os.getenv("MK4_STT_CPU_THREADS", "4"))

# TTS: Apache-2.0 Qwen3-TTS 12Hz 0.6B CustomVoice. Sohee is the native Korean
# preset. A local model directory can override the managed Hugging Face download.
VOICE_TTS_MODEL = os.getenv(
    "MK4_TTS_MODEL",
    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
).strip() or "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
VOICE_TTS_MODEL_PATH = os.getenv("MK4_TTS_MODEL_PATH", "").strip()
VOICE_TTS_SPEAKER = os.getenv("MK4_TTS_SPEAKER", "Sohee").strip() or "Sohee"
VOICE_TTS_LANGUAGE = os.getenv("MK4_TTS_LANGUAGE", "Korean").strip() or "Korean"
VOICE_TTS_INSTRUCT = os.getenv(
    "MK4_TTS_INSTRUCT",
    "차분하고 안정적인 말투로 자연스럽게 말해줘.",
).strip()
VOICE_TTS_DEVICE = os.getenv("MK4_TTS_DEVICE", "auto").strip() or "auto"
VOICE_TTS_DTYPE = os.getenv("MK4_TTS_DTYPE", "auto").strip() or "auto"

# First-run Qwen3-TTS download is ~2.5 GB, so preparation gets a separate timeout.
VOICE_PREPARE_TIMEOUT_SECONDS = float(os.getenv("MK4_VOICE_PREPARE_TIMEOUT_SECONDS", "1800"))
VOICE_INFERENCE_TIMEOUT_SECONDS = float(os.getenv("MK4_VOICE_INFERENCE_TIMEOUT_SECONDS", "300"))
VOICE_MAX_AUDIO_BYTES = int(os.getenv("MK4_VOICE_MAX_AUDIO_BYTES", str(12 * 1024 * 1024)))
VOICE_MAX_TTS_CHARS = int(os.getenv("MK4_VOICE_MAX_TTS_CHARS", "6000"))

OLLAMA_EXCLUDED_MODELS: frozenset[str] = frozenset(
    name.strip()
    for name in os.getenv("OLLAMA_EXCLUDED_MODELS", "embeddinggemma:latest,nomic-embed-text").split(",")
    if name.strip()
)
