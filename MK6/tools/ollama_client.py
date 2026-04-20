"""Ollama HTTP 클라이언트 — 임베딩 + 텍스트 생성 + 모델 목록."""
from __future__ import annotations

import httpx

from .. import config

# 공유 클라이언트 — 연결 풀 재사용. 임베딩처럼 짧은 요청이 여러 번 올 때 효과적이다.
# timeout은 요청별로 따로 지정하므로 여기서는 설정하지 않는다.
_shared_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            # pool=None: 연결 대기 무제한.
            # asyncio.gather로 대량 임베딩 요청을 동시 발화할 때 PoolTimeout 방지.
            timeout=httpx.Timeout(
                connect=5.0,
                read=config.EMBEDDING_TIMEOUT_SECONDS,
                write=5.0,
                pool=None,
            ),
        )
    return _shared_client

# Ollama가 families 메타데이터로 분류하는 임베딩 전용 패밀리.
# /api/tags 응답의 details.families 값을 기준으로 필터링한다.
# (문자열 휴리스틱이 아닌 Ollama 자체 분류 메타데이터 사용)
_EMBEDDING_ONLY_FAMILIES: frozenset[str] = frozenset({"nomic-bert", "bert", "clip"})


async def get_embedding(text: str) -> list[float]:
    """nomic-embed-text (또는 설정된 모델)로 임베딩 벡터를 반환한다.

    공유 클라이언트를 사용해 연결 풀을 재사용한다.

    Raises:
        httpx.HTTPError: 네트워크 오류 또는 Ollama 오류 응답
    """
    url = f"{config.OLLAMA_HOST}/api/embeddings"
    client = _get_client()
    r = await client.post(
        url,
        json={"model": config.EMBEDDING_MODEL_NAME, "prompt": text},
        # 클라이언트 레벨 timeout 사용 (pool=None 포함). per-request 오버라이드 없음.
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
    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT_SECONDS) as client:
            r = await client.post(
                url,
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": config.OLLAMA_NUM_PREDICT},
                },
            )
    except httpx.ReadTimeout:
        raise TimeoutError(
            f"Ollama 모델 '{model_name}'이 {config.OLLAMA_TIMEOUT_SECONDS:.0f}초 안에 응답하지 않았습니다. "
            "모델이 처음 로드 중이거나 머신 자원이 부족할 수 있습니다. "
            "잠시 후 다시 시도하거나 OLLAMA_TIMEOUT_SECONDS 값을 늘려 주세요."
        )

    if r.status_code == 400:
        raise ValueError(
            f"Ollama가 모델 '{model_name}'로 생성 요청을 거부했습니다 (400). "
            "임베딩 전용 모델을 선택했거나 모델 이름이 올바르지 않을 수 있습니다."
        )
    r.raise_for_status()
    return r.json()["response"]


async def chat(
    system: str,
    user: str,
    model: str | None = None,
) -> str:
    """Ollama chat 엔드포인트로 텍스트를 생성한다 (non-streaming).

    system 메시지와 user 메시지를 분리해 전달한다.

    Args:
        system: 시스템 메시지 (AI의 역할/인식 상태 정의)
        user:   사용자 메시지
        model:  사용할 모델 이름. None이면 config.OLLAMA_MODEL_NAME 사용.

    Raises:
        ValueError: 모델명 미설정 또는 Ollama 거부 (400)
        TimeoutError: 응답 타임아웃
        httpx.HTTPError: 그 외 네트워크/HTTP 오류
    """
    model_name = model or config.OLLAMA_MODEL_NAME
    if not model_name:
        raise ValueError(
            "OLLAMA_MODEL_NAME 환경변수가 설정되지 않았습니다. "
            "UI에서 모델을 선택하거나 환경변수를 지정하세요."
        )
    url = f"{config.OLLAMA_HOST}/api/chat"
    try:
        async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT_SECONDS) as client:
            r = await client.post(
                url,
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "stream": False,
                    "options": {"num_predict": config.OLLAMA_NUM_PREDICT},
                },
            )
    except httpx.ReadTimeout:
        raise TimeoutError(
            f"Ollama 모델 '{model_name}'이 {config.OLLAMA_TIMEOUT_SECONDS:.0f}초 안에 응답하지 않았습니다."
        )

    if r.status_code == 400:
        raise ValueError(
            f"Ollama가 모델 '{model_name}'로 chat 요청을 거부했습니다 (400). "
            "임베딩 전용 모델을 선택했거나 모델 이름이 올바르지 않을 수 있습니다."
        )
    r.raise_for_status()
    return r.json()["message"]["content"]


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
            name: str = m["name"]
            # 명시적 제외 모델 (패밀리로 구분 불가한 임베딩 전용 모델 등)
            if name in config.OLLAMA_EXCLUDED_MODELS:
                continue
            details = m.get("details") or {}
            # Ollama 버전에 따라 "families"(복수) 또는 "family"(단수)로 반환
            families: list[str] = details.get("families") or []
            if not families:
                singular = details.get("family") or ""
                if singular:
                    families = [singular]
            # 모든 패밀리가 임베딩 전용이면 제외
            if families and all(f in _EMBEDDING_ONLY_FAMILIES for f in families):
                continue
            result.append(name)
        return result

    except Exception:
        return []
