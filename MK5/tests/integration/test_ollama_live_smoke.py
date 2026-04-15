from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ollama_client import OllamaClient, OllamaClientError

DEFAULT_MODEL = os.getenv('MK5_SMOKE_MODEL', 'gemma4:e2b')


def main() -> None:
    client = OllamaClient(timeout_seconds=30.0)
    ok, error = client.health_check()
    if not ok:
        print(f'SKIP: Ollama unavailable - {error}')
        return

    try:
        result = client.chat(
            model_name=DEFAULT_MODEL,
            messages=[
                {
                    'role': 'system',
                    'content': '짧고 자연스러운 한국어 한 문장으로만 답해라.',
                },
                {
                    'role': 'user',
                    'content': 'MK5 smoke test 한 줄만 말해줘.',
                },
            ],
            options={'temperature': 0.1},
        )
    except OllamaClientError as exc:
        raise RuntimeError(f'OLLAMA smoke test failed: {exc}') from exc

    assert isinstance(result.content, str) and result.content.strip()
    print(f'PASS: ollama live smoke ({result.model}) -> {result.content}')


if __name__ == '__main__':
    main()
