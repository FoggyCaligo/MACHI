import requests

from config import OLLAMA_BASE_URL, OLLAMA_MODEL


class OllamaClient:
    def chat(self, messages: list[dict]) -> str:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
        }
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]
