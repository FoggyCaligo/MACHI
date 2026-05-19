from __future__ import annotations

import httpx

from . import config


async def get_embedding(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{config.OLLAMA_HOST}/api/embeddings", json={"model": config.OLLAMA_EMBEDDING_MODEL, "prompt": text})
        response.raise_for_status()
        return [float(x) for x in response.json().get("embedding", [])]


async def chat(system: str, user: str, model: str | None = None) -> str:
    selected = model or config.OLLAMA_MODEL_NAME
    async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{config.OLLAMA_HOST}/api/chat",
            json={"model": selected, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "options": {"num_predict": config.OLLAMA_NUM_PREDICT}},
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "")


async def list_models() -> list[str]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{config.OLLAMA_HOST}/api/tags")
        response.raise_for_status()
        models = []
        for item in response.json().get("models", []):
            name = item.get("name")
            families = set(item.get("details", {}).get("families") or [])
            if not name or name in config.OLLAMA_EXCLUDED_MODELS:
                continue
            if families and families.issubset({"nomic-bert", "bert", "clip"}):
                continue
            models.append(name)
        return models
