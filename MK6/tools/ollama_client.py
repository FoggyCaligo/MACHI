"""Ollama HTTP 클라이언트 — 임베딩 + 텍스트 생성 + 모델 목록."""
from __future__ import annotations

import httpx

from .. import config

# Ollama가 families 메타데이터로 분류하는 임베딩 전용 패밀리.
# /api/tags 응답의 details.families 값을 기준으로 필터링한다.
# (문자열 휴리스틱이 아닌 Ollama 자체 분류 메타데이터 사용)
_EMBEDDING_ONLY_FAMILIES: frozenset[str] = frozenset({"nomic-bert", "bert", "clip"})


async def get_embedding(text: str) -> list[float]:
    """nomic-embed-text (또는 설정된 모델)로 임베딩 벡터를 반환한다.

    Raises:
        httpx.HTTPError: 네트워크 오류 또는 Ollama 오류 응답
    """
    url = f"{config.OLLAMA_HOST}/api/embeddings"
    async with httpx.AsyncClient(timeout=config.EMBEDDING_TIMEOUT_SECONDS) as client:
        r = await client.post(
            url,
            json={"model": config.EMBEDDING_MODEL_NAME, "prompt": text},
        )
        r.raise_for_status()
        return r.json()["embedding"]


async def generate(prompt: str, model: str | None = None) -> str:
    """Ollama generate 엔드포인트로 텍스트를 생성한다 (non-streaming).

    Args:
        prompt: 입력 프롬프트
        model:  사용할 모델 이름. None이면 config.OLLAMA_MODEL_NAME 사용.

    Raises:
        ValueError: 모델명이 설정되지 않은 경우
        httpx.HTTPError: 네트워크 오류 또는 Ollama 오류 응답
    """
    model_name = model or config.OLLAMA_MODEL_NAME
    if not model_name:
        raise ValueError(
            "OLLAMA_MODEL_NAME 환경변수가 설정되지 않았습니다. "
            ".env 또는 환경변수에서 모델 이름을 지정하거나, "
            "UI에서 모델을 선택하세요."
        )
    url = f"{config.OLLAMA_HOST}/api/generate"
    async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT_SECONDS) as client:
        r = await client.post(
            url,
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
            },
        )
        r.raise_for_status()
        return r.json()["response"]


async def list_models() -> list[str]:
    """Ollama에 설치된 텍스트 생성 가능 모델 목록을 반환한다.

    /api/tags 응답의 details.families 메타데이터를 사용해
    임베딩 전용 모델(nomic-bert, bert, clip 등)을 제외한다.

    Returns:
        생성 모델 이름 리스트 (예: ["gemma3:4b", "llama3:latest"])
        Ollama에 접속할 수 없으면 빈 리스트 반환.
    """
    url = f"{config.OLLAMA_HOST}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        result: list[str] = []
        for m in data.get("models", []):
            details = m.get("details") or {}
            families: list[str] = details.get("families") or []
            # Ollama가 분류한 families 중 생성 불가 패밀리만 있으면 제외
            if families and all(f in _EMBEDDING_ONLY_FAMILIES for f in families):
                continue
            result.append(m["name"])
        return result

    except Exception:
        return []
