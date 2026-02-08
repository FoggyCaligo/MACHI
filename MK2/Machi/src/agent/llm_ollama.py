# src/agent/llm_ollama.py
import os
import requests

class OllamaLLM:
    def __init__(self):
        self.base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.model_chat = os.getenv("MODEL_CHAT", "llama3.1:8b")
        self.model_fast = os.getenv("MODEL_FAST", self.model_chat)

        # 긴 응답이 필요하면 올리되, 기본은 짧게: "서버가 안 죽게"
        self.timeout_sec = int(os.getenv("OLLAMA_TIMEOUT_SEC", "1000"))

    def chat(self, prompt: str, fast: bool = False) -> str:
        model = self.model_fast if fast else self.model_chat
        url = f"{self.base}/api/generate"

        try:
            r = requests.post(
                url,
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=self.timeout_sec,
            )

            # Ollama가 아니거나 경로가 다르면 404가 나올 수 있음
            if r.status_code == 404:
                return (
                    "[LLM_BACKEND_ERROR]\n"
                    f"- {url} 에서 404\n"
                    "- Ollama가 아니거나 API 경로가 다름\n"
                )

            r.raise_for_status()
            return (r.json().get("response") or "").strip()

        except requests.exceptions.ReadTimeout:
            return (
                "[LLM_BACKEND_TIMEOUT]\n"
                f"- Ollama 응답이 {self.timeout_sec}s 안에 오지 않았어.\n"
                "- 모델이 아직 다운로드/로딩 중이거나, 너무 무거워서 첫 응답이 늦을 수 있어.\n"
                "- 해결: 더 작은 모델 사용(qwen2.5:3b 등) 또는 OLLAMA_TIMEOUT_SEC 증가.\n"
            )
        except requests.exceptions.ConnectionError:
            return (
                "[LLM_BACKEND_DOWN]\n"
                f"- {url} 연결 실패 (Ollama 꺼짐/포트 다름)\n"
            )
        except Exception as e:
            return f"[LLM_BACKEND_ERROR] {type(e).__name__}: {e}"
