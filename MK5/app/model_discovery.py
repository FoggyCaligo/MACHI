from __future__ import annotations

from dataclasses import dataclass

from config import MODEL_DISCOVERY_TIMEOUT_SECONDS
from tools.ollama_client import OllamaClient

DEFAULT_MODEL_NAME = 'mk5-graph-core'


@dataclass(slots=True)
class ModelCatalog:
    default_model: str
    models: list[dict[str, str]]
    ollama_available: bool
    error: str | None = None


def discover_model_catalog(default_model: str = DEFAULT_MODEL_NAME) -> ModelCatalog:
    client = OllamaClient(timeout_seconds=MODEL_DISCOVERY_TIMEOUT_SECONDS)
    ok, error = client.health_check()
    if ok:
        try:
            models = client.list_models()
            if default_model and all(item['name'] != default_model for item in models):
                models.insert(0, {'name': default_model, 'parameter_size': '', 'quantization_level': ''})
            return ModelCatalog(
                default_model=default_model,
                models=models,
                ollama_available=True,
                error=None,
            )
        except Exception as exc:
            error = str(exc)
    return ModelCatalog(
        default_model=default_model,
        models=[{'name': default_model, 'parameter_size': '', 'quantization_level': ''}],
        ollama_available=False,
        error=error,
    )
