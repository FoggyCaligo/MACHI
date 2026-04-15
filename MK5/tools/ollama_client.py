from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
DEFAULT_OLLAMA_TIMEOUT_SECONDS = float(os.getenv('OLLAMA_TIMEOUT_SECONDS', '120.0'))


class OllamaClientError(RuntimeError):
    """Base error for Ollama transport failures."""


class OllamaConnectionError(OllamaClientError):
    """Raised when the Ollama server cannot be reached."""


class OllamaRequestError(OllamaClientError):
    """Raised when Ollama returns an HTTP error."""


class OllamaResponseError(OllamaClientError):
    """Raised when Ollama returns malformed or unusable data."""


class OllamaModelNotFoundError(OllamaRequestError):
    """Raised when the requested model does not exist locally."""


@dataclass(frozen=True, slots=True)
class OllamaModelEntry:
    name: str
    parameter_size: str = ''
    quantization_level: str = ''


@dataclass(frozen=True, slots=True)
class OllamaChatResult:
    model: str
    content: str
    raw: dict[str, Any]


@dataclass(slots=True)
class OllamaClient:
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip('/')

    def health_check(self) -> tuple[bool, str | None]:
        try:
            self.tags()
            return True, None
        except OllamaClientError as exc:
            return False, str(exc)

    def tags(self) -> list[OllamaModelEntry]:
        payload = self._request_json('GET', '/api/tags')
        raw_models = payload.get('models') or []
        models: list[OllamaModelEntry] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            details = item.get('details') or {}
            models.append(
                OllamaModelEntry(
                    name=name,
                    parameter_size=str(details.get('parameter_size') or ''),
                    quantization_level=str(details.get('quantization_level') or ''),
                )
            )
        return models

    def list_models(self) -> list[dict[str, str]]:
        return [
            {
                'name': item.name,
                'parameter_size': item.parameter_size,
                'quantization_level': item.quantization_level,
            }
            for item in self.tags()
        ]

    def chat(
        self,
        *,
        model_name: str,
        messages: list[dict[str, str]],
        stream: bool = False,
        options: dict[str, Any] | None = None,
        response_format: str | dict[str, Any] | None = None,
    ) -> OllamaChatResult:
        if not model_name.strip():
            raise OllamaResponseError('model_name is required')
        payload: dict[str, Any] = {
            'model': model_name,
            'stream': stream,
            'messages': messages,
        }
        if options:
            payload['options'] = options
        if response_format is not None:
            payload['format'] = response_format
        raw = self._request_json('POST', '/api/chat', payload)
        message = raw.get('message') or {}
        if not isinstance(message, dict):
            raise OllamaResponseError('OLLAMA returned a non-dict message payload')
        content = str(message.get('content') or '').strip()
        if not content:
            raise OllamaResponseError('OLLAMA returned empty content')
        model = str(raw.get('model') or model_name)
        return OllamaChatResult(model=model, content=content, raw=raw)

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f'{self.base_url}{path}'
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json'} if method.upper() == 'POST' else {}
        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_bytes = response.read()
        except HTTPError as exc:
            body = exc.read().decode('utf-8', errors='ignore')
            self._raise_http_error(exc.code, body or exc.reason)
        except (URLError, TimeoutError, OSError) as exc:
            raise OllamaConnectionError(str(exc)) from exc

        try:
            decoded = json.loads(raw_bytes.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaResponseError('OLLAMA returned invalid JSON') from exc

        if not isinstance(decoded, dict):
            raise OllamaResponseError('OLLAMA returned a non-object JSON payload')
        return decoded

    def _raise_http_error(self, status_code: int, body: str) -> None:
        normalized = body.lower()
        if status_code == 404 and ('model' in normalized or 'not found' in normalized):
            raise OllamaModelNotFoundError(f'OLLAMA model not found: {body}')
        raise OllamaRequestError(f'OLLAMA HTTP {status_code}: {body}')
