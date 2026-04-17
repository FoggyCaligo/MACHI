from __future__ import annotations

import os
from typing import Any


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, '').strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_optional_int(name: str) -> int | None:
    raw = os.getenv(name, '').strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, '').strip().lower()
    if not raw:
        return default
    if raw in {'1', 'true', 'yes', 'on'}:
        return True
    if raw in {'0', 'false', 'no', 'off'}:
        return False
    return default


OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
OLLAMA_TIMEOUT_SECONDS = _env_float('OLLAMA_TIMEOUT_SECONDS', 120.0)
MODEL_DISCOVERY_TIMEOUT_SECONDS = _env_float('MODEL_DISCOVERY_TIMEOUT_SECONDS', 1.5)

VERBALIZER_OLLAMA_TIMEOUT_SECONDS = _env_float('OLLAMA_VERBALIZER_TIMEOUT_SECONDS', 180.0)
VERBALIZER_TEMPERATURE = _env_float('VERBALIZER_TEMPERATURE', 0.2)
VERBALIZER_NUM_PREDICT = _env_optional_int('VERBALIZER_NUM_PREDICT')

SEARCH_MAX_RESULTS = _env_int('SEARCH_MAX_RESULTS', 4)
SEARCH_BACKEND_TIMEOUT_SECONDS = _env_float('SEARCH_BACKEND_TIMEOUT_SECONDS', 4.0)

MODEL_FEEDBACK_TIMEOUT_SECONDS = _env_float('MODEL_FEEDBACK_TIMEOUT_SECONDS', 20.0)
MODEL_FEEDBACK_TEMPERATURE = _env_float('MODEL_FEEDBACK_TEMPERATURE', 0.0)
MODEL_FEEDBACK_NUM_PREDICT = _env_optional_int('MODEL_FEEDBACK_NUM_PREDICT')

MODEL_EDGE_ASSERTION_TIMEOUT_SECONDS = _env_float('MODEL_EDGE_ASSERTION_TIMEOUT_SECONDS', 25.0)
MODEL_EDGE_ASSERTION_TEMPERATURE = _env_float('MODEL_EDGE_ASSERTION_TEMPERATURE', 0.1)
MODEL_EDGE_ASSERTION_NUM_PREDICT = _env_optional_int('MODEL_EDGE_ASSERTION_NUM_PREDICT')

CONNECT_TYPE_PROMOTION_THRESHOLD = _env_int('CONNECT_TYPE_PROMOTION_THRESHOLD', 3)
CONNECT_TYPE_PROMOTION_MAX_SCAN = _env_int('CONNECT_TYPE_PROMOTION_MAX_SCAN', 500)

REQUEST_TIMEOUT_MS = _env_int('REQUEST_TIMEOUT_MS', 300000)
REVISION_RULE_OVERRIDES_PATH = os.getenv(
    'REVISION_RULE_OVERRIDES_PATH',
    'data/revision_rule_overrides.auto.json',
).strip()
REVISION_RULE_PROFILE = os.getenv('REVISION_RULE_PROFILE', '').strip()
REVISION_RULE_OVERRIDES_STRICT = _env_bool('REVISION_RULE_OVERRIDES_STRICT', False)


def build_ollama_options(*, temperature: float, num_predict: int | None = None) -> dict[str, Any]:
    options: dict[str, Any] = {'temperature': temperature}
    if num_predict is not None:
        options['num_predict'] = num_predict
    return options
