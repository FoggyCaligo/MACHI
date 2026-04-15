from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaClientError(RuntimeError):
    pass


class OllamaConnectionError(OllamaClientError):
    pass


class OllamaRequestError(OllamaClientError):
    pass


class OllamaResponseError(OllamaClientError):
    pass


class OllamaModelNotFoundError(OllamaRequestError):
    pass


@dataclass(slots=True)
class OllamaChatResult:
    content: str
    raw: dict[str, Any]


@dataclass(slots=True)
class OllamaClient:
    base_url: str | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.base_url is None:
            self.base_url = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
        self.base_url = self.base_url.rstrip('/')
        if self.timeout_seconds is None:
            self.timeout_seconds = float(os.getenv('OLLAMA_TIMEOUT_SECONDS', '120'))

    def health_check(self) -> bool:
        try:
            self.tags()
            return True
        except OllamaClientError:
            return False

    def tags(self) -> dict[str, Any]:
        return self._request_json('GET', '/api/tags')

    def list_models(self) -> list[dict[str, Any]]:
        payload = self.tags()
        models = payload.get('models')
        return list(models) if isinstance(models, list) else []

    def chat(
        self,
        *,
        model_name: str,
        messages: list[dict[str, Any]],
        stream: bool = False,
        options: dict[str, Any] | None = None,
        response_format: str | dict[str, Any] | None = None,
    ) -> OllamaChatResult:
        payload: dict[str, Any] = {
            'model': model_name,
            'messages': messages,
            'stream': stream,
        }
        if options:
            payload['options'] = options
        if response_format is not None:
            if response_format == 'json':
                payload['format'] = 'json'
            else:
                payload['format'] = response_format
        raw = self._request_json('POST', '/api/chat', payload)
        message = raw.get('message') or {}
        content = str(message.get('content') or '').strip()
        if not content:
            raise OllamaResponseError('OLLAMA returned empty content')
        return OllamaChatResult(content=content, raw=raw)

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        request = Request(
            f'{self.base_url}{path}',
            data=data,
            headers={'Content-Type': 'application/json'},
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                try:
                    return json.loads(response.read().decode('utf-8'))
                except json.JSONDecodeError as exc:
                    raise OllamaResponseError('OLLAMA returned invalid JSON') from exc
        except HTTPError as exc:
            body = exc.read().decode('utf-8', errors='ignore')
            message = body or exc.reason
            if exc.code == 404 and 'model' in message.lower():
                raise OllamaModelNotFoundError(message) from exc
            raise OllamaRequestError(f'OLLAMA HTTP {exc.code}: {message}') from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise OllamaConnectionError(str(exc)) from exc
