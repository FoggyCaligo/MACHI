from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from MK6_1.tools import ollama_client


class _FakeClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []
        self.is_closed = False

    async def post(self, url: str, json: dict) -> httpx.Response:
        self.calls.append((url, json))
        response = self._responses.pop(0)
        response._request = httpx.Request("POST", url, json=json)
        return response


class OllamaClientEmbeddingTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_embedding_falls_back_to_current_embed_api(self) -> None:
        client = _FakeClient(
            [
                httpx.Response(404, json={"error": "not found"}),
                httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]}),
            ]
        )

        with patch.object(ollama_client, "_get_client", return_value=client):
            embedding = await ollama_client.get_embedding("hello")

        self.assertEqual(embedding, [0.1, 0.2, 0.3])
        self.assertTrue(client.calls[0][0].endswith("/api/embeddings"))
        self.assertEqual(client.calls[0][1]["prompt"], "hello")
        self.assertTrue(client.calls[1][0].endswith("/api/embed"))
        self.assertEqual(client.calls[1][1]["input"], "hello")

    async def test_get_embedding_raises_clear_error_for_missing_model(self) -> None:
        client = _FakeClient([httpx.Response(400, json={"error": "model not found"})])

        with patch.object(ollama_client, "_get_client", return_value=client):
            with self.assertRaisesRegex(ValueError, "nomic-embed-text"):
                await ollama_client.get_embedding("hello")


if __name__ == "__main__":
    unittest.main()
