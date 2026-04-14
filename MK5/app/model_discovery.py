from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen

OLLAMA_TAGS_URL = 'http://127.0.0.1:11434/api/tags'
DEFAULT_MODEL_NAME = 'mk5-graph-core'


@dataclass(slots=True)
class ModelCatalog:
    default_model: str
    models: list[dict[str, str]]
    ollama_available: bool
    error: str | None = None


def _normalize_model_entry(raw: dict) -> dict[str, str]:
    details = raw.get('details') or {}
    return {
        'name': str(raw.get('name') or ''),
        'parameter_size': str(details.get('parameter_size') or ''),
        'quantization_level': str(details.get('quantization_level') or ''),
    }


def discover_model_catalog(default_model: str = DEFAULT_MODEL_NAME) -> ModelCatalog:
    try:
        with urlopen(OLLAMA_TAGS_URL, timeout=1.5) as response:
            payload = json.loads(response.read().decode('utf-8'))
        raw_models = payload.get('models') or []
        models = [_normalize_model_entry(item) for item in raw_models if item.get('name')]
        if default_model and all(item['name'] != default_model for item in models):
            models.insert(0, {'name': default_model, 'parameter_size': '', 'quantization_level': ''})
        return ModelCatalog(
            default_model=default_model,
            models=models,
            ollama_available=True,
            error=None,
        )
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return ModelCatalog(
            default_model=default_model,
            models=[{'name': default_model, 'parameter_size': '', 'quantization_level': ''}],
            ollama_available=False,
            error=str(exc),
        )
