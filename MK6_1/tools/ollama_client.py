"""Ollama HTTP client helpers for embeddings, text generation, and model listing."""
from __future__ import annotations

from typing import Any

import httpx

from .. import config

_shared_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=config.EMBEDDING_TIMEOUT_SECONDS,
                write=5.0,
                pool=None,
            ),
        )
    return _shared_client


_EMBEDDING_ONLY_FAMILIES: frozenset[str] = frozenset({"nomic-bert", "bert", "clip"})


def _generation_options(*, num_predict: int | None = None) -> dict:
    return {"num_predict": num_predict if num_predict is not None else config.OLLAMA_NUM_PREDICT}


def _generation_payload(
    base: dict,
    *,
    num_predict: int | None = None,
    think: bool | None = None,
    response_format: str | dict[str, Any] | None = None,
) -> dict:
    payload = {
        **base,
        "stream": False,
        "options": _generation_options(num_predict=num_predict),
    }
    payload["think"] = config.OLLAMA_THINK if think is None else think
    if response_format is not None:
        payload["format"] = response_format
    return payload


async def get_embedding(text: str) -> list[float]:
    """Return an embedding vector from Ollama for the configured embedding model."""
    client = _get_client()
    r = await client.post(
        f"{config.OLLAMA_HOST}/api/embeddings",
        json={"model": config.EMBEDDING_MODEL_NAME, "prompt": text},
    )
    if r.status_code == 404:
        r = await client.post(
            f"{config.OLLAMA_HOST}/api/embed",
            json={"model": config.EMBEDDING_MODEL_NAME, "input": text},
        )

    if r.status_code == 404:
        raise RuntimeError(
            "Ollama embedding API was not found at either /api/embeddings or /api/embed."
        )
    if r.status_code == 400:
        raise ValueError(
            f"Ollama could not serve embedding model '{config.EMBEDDING_MODEL_NAME}'. "
            "Install it first with `ollama pull nomic-embed-text` or set EMBEDDING_MODEL_NAME."
        )
    r.raise_for_status()

    data = r.json()
    embedding = data.get("embedding")
    if isinstance(embedding, list):
        return embedding

    embeddings = data.get("embeddings")
    if isinstance(embeddings, list) and embeddings:
        first = embeddings[0]
        if isinstance(first, list):
            return first

    raise RuntimeError("Ollama embedding response did not include an embedding vector.")


async def generate(prompt: str, model: str | None = None) -> str:
    """Generate text with Ollama's non-streaming generate API."""
    model_name = model or config.OLLAMA_MODEL_NAME
    if not model_name:
        raise ValueError(
            "OLLAMA_MODEL_NAME environment variable is not configured. "
            "Set it in your environment or choose a model in the UI."
        )
    url = f"{config.OLLAMA_HOST}/api/generate"
    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT_SECONDS) as client:
            r = await client.post(
                url,
                json=_generation_payload(
                    {
                        "model": model_name,
                        "prompt": prompt,
                    }
                ),
            )
    except httpx.ReadTimeout:
        raise TimeoutError(
            f"Ollama model '{model_name}' did not respond within "
            f"{config.OLLAMA_TIMEOUT_SECONDS:.0f} seconds."
        )

    if r.status_code == 400:
        raise ValueError(
            f"Ollama rejected generate request for model '{model_name}' (400). "
            "The model name may be wrong or an embedding-only model may have been selected."
        )
    r.raise_for_status()
    return r.json()["response"]


async def chat(
    system: str,
    user: str,
    model: str | None = None,
    *,
    num_predict: int | None = None,
    think: bool | None = None,
    response_format: str | dict[str, Any] | None = None,
) -> str:
    """Generate text with Ollama's non-streaming chat API."""
    model_name = model or config.OLLAMA_MODEL_NAME
    if not model_name:
        raise ValueError(
            "OLLAMA_MODEL_NAME environment variable is not configured. "
            "Choose a model in the UI or set it in your environment."
        )
    url = f"{config.OLLAMA_HOST}/api/chat"
    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT_SECONDS) as client:
            r = await client.post(
                url,
                json=_generation_payload(
                    {
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                    num_predict=num_predict,
                    think=think,
                    response_format=response_format,
                ),
            )
    except httpx.ReadTimeout:
        raise TimeoutError(
            f"Ollama model '{model_name}' did not respond within "
            f"{config.OLLAMA_TIMEOUT_SECONDS:.0f} seconds."
        )

    if r.status_code == 400:
        raise ValueError(
            f"Ollama rejected chat request for model '{model_name}' (400). "
            "The model name may be wrong or an embedding-only model may have been selected."
        )
    r.raise_for_status()

    data = r.json()
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(
            "Ollama chat response content was empty. "
            f"model='{model_name}', "
            f"http_status={r.status_code}, "
            f"done={data.get('done')!r}, "
            f"done_reason={data.get('done_reason')!r}, "
            f"think={config.OLLAMA_THINK!r}, "
            f"num_predict={config.OLLAMA_NUM_PREDICT}"
        )
    return content


async def list_models() -> list[str]:
    """Return Ollama models that look usable for text generation."""
    url = f"{config.OLLAMA_HOST}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        result: list[str] = []
        for m in data.get("models", []):
            name: str = m["name"]
            if name in config.OLLAMA_EXCLUDED_MODELS:
                continue
            details = m.get("details") or {}
            families: list[str] = details.get("families") or []
            if not families:
                singular = details.get("family") or ""
                if singular:
                    families = [singular]
            if families and all(f in _EMBEDDING_ONLY_FAMILIES for f in families):
                continue
            result.append(name)
        return result

    except Exception:
        return []
