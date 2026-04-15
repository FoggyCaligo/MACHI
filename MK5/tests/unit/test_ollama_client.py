from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from tools.ollama_client import (
    OllamaClient,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaResponseError,
)


class _OllamaMockHandler(BaseHTTPRequestHandler):
    response_map: dict[str, tuple[int, dict[str, Any]]] = {}

    def do_GET(self) -> None:  # noqa: N802
        status_code, body = self.response_map.get(self.path, (404, {'error': 'not found'}))
        self._write_json(status_code, body)

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get('Content-Length', '0'))
        raw_body = self.rfile.read(content_length) if content_length else b''
        if self.path == '/api/chat' and raw_body:
            try:
                payload = json.loads(raw_body.decode('utf-8'))
            except json.JSONDecodeError:
                payload = {}
            model = str(payload.get('model') or '')
            if model == 'missing-model':
                self._write_json(404, {'error': 'model not found'})
                return
            if model == 'empty-model':
                self._write_json(200, {'message': {'content': ''}})
                return

        status_code, body = self.response_map.get(self.path, (404, {'error': 'not found'}))
        self._write_json(status_code, body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _write_json(self, status_code: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class OllamaMockServer:
    def __init__(self, response_map: dict[str, tuple[int, dict[str, Any]]]) -> None:
        handler = type('ConfiguredOllamaMockHandler', (_OllamaMockHandler,), {})
        handler.response_map = response_map
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f'http://{host}:{port}'

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)


def test_ollama_client_chat_and_tags_success() -> None:
    server = OllamaMockServer(
        {
            '/api/tags': (
                200,
                {
                    'models': [
                        {
                            'name': 'gemma4:e2b',
                            'details': {
                                'parameter_size': '2B',
                                'quantization_level': 'Q4_K_M',
                            },
                        }
                    ]
                },
            ),
            '/api/chat': (
                200,
                {
                    'model': 'gemma4:e2b',
                    'message': {'content': '안녕하세요. MK5 응답입니다.'},
                },
            ),
        }
    )
    server.start()
    try:
        client = OllamaClient(base_url=server.base_url, timeout_seconds=2.0)
        models = client.list_models()
        assert models == [
            {
                'name': 'gemma4:e2b',
                'parameter_size': '2B',
                'quantization_level': 'Q4_K_M',
            }
        ]
        result = client.chat(
            model_name='gemma4:e2b',
            messages=[{'role': 'user', 'content': '테스트'}],
            response_format='json',
        )
        assert result.model == 'gemma4:e2b'
        assert result.content == '안녕하세요. MK5 응답입니다.'
    finally:
        server.stop()


def test_ollama_client_model_not_found_error() -> None:
    server = OllamaMockServer(
        {
            '/api/tags': (200, {'models': []}),
            '/api/chat': (200, {'message': {'content': 'unused'}}),
        }
    )
    server.start()
    try:
        client = OllamaClient(base_url=server.base_url, timeout_seconds=2.0)
        try:
            client.chat(model_name='missing-model', messages=[{'role': 'user', 'content': '테스트'}])
            raise AssertionError('Expected OllamaModelNotFoundError')
        except OllamaModelNotFoundError:
            pass
    finally:
        server.stop()


def test_ollama_client_empty_content_error() -> None:
    server = OllamaMockServer(
        {
            '/api/tags': (200, {'models': []}),
            '/api/chat': (200, {'message': {'content': 'unused'}}),
        }
    )
    server.start()
    try:
        client = OllamaClient(base_url=server.base_url, timeout_seconds=2.0)
        try:
            client.chat(model_name='empty-model', messages=[{'role': 'user', 'content': '테스트'}])
            raise AssertionError('Expected OllamaResponseError')
        except OllamaResponseError:
            pass
    finally:
        server.stop()


def test_ollama_client_health_check_connection_failure() -> None:
    client = OllamaClient(base_url='http://127.0.0.1:9', timeout_seconds=0.2)
    ok, error = client.health_check()
    assert ok is False
    assert isinstance(error, str) and error
    try:
        client.tags()
        raise AssertionError('Expected OllamaConnectionError')
    except OllamaConnectionError:
        pass
