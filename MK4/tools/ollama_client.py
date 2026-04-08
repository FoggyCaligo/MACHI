import requests

from config import OLLAMA_BASE_URL, OLLAMA_DEFAULT_MODEL


DEFAULT_TIMEOUT = 150
DEFAULT_NUM_PREDICT = 768
DEFAULT_TRUNCATED_NOTICE = "\n\n[주의: 답변이 길이 제한으로 중간 종료되었을 수 있습니다. 더 짧게 다시 요청해 주세요.]"


class OllamaClient:
    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
        num_predict: int = DEFAULT_NUM_PREDICT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_predict = num_predict

    def _sanitize_messages(self, messages: list[dict]) -> list[dict]:
        sanitized: list[dict] = []

        for msg in messages:
            role = (msg.get("role") or "").strip()
            content = str(msg.get("content") or "")

            if not role:
                continue

            if not content.strip():
                continue

            if role == "system":
                content = content.replace("<|think|>", "").strip()

            sanitized.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        return sanitized

    def _build_payload(self, messages: list[dict], model_name: str) -> dict:
        return {
            "model": model_name,
            "messages": self._sanitize_messages(messages),
            "stream": False,
            "think": False,
            "options": {
                "num_predict": self.num_predict,
            },
        }

    def _summarize_response(self, data: dict) -> dict:
        message = data.get("message") or {}
        content = (message.get("content") or "").strip()
        thinking = (message.get("thinking") or "").strip()

        return {
            "model": data.get("model"),
            "done": data.get("done"),
            "done_reason": data.get("done_reason"),
            "content_len": len(content),
            "has_thinking": bool(thinking),
            "thinking_len": len(thinking),
            "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"),
            "total_duration": data.get("total_duration"),
            "load_duration": data.get("load_duration"),
        }

    def _classify_empty_reply(self, data: dict) -> str:
        message = data.get("message") or {}
        content = (message.get("content") or "").strip()
        thinking = (message.get("thinking") or "").strip()
        done_reason = data.get("done_reason")

        if content:
            return "ok"

        if thinking and done_reason == "length":
            return (
                "EMPTY_REPLY_THINKING_TOKEN_BUDGET: "
                "최종 답변(content) 없이 thinking만 생성하다가 num_predict 한도에 걸렸습니다. "
                "think=false가 무시되었거나 모델이 여전히 reasoning trace를 생성한 상태일 수 있습니다."
            )

        if thinking and not content:
            return (
                "EMPTY_REPLY_THINKING_ONLY: "
                "최종 답변(content)은 비어 있고 thinking만 존재합니다. "
                "think=false가 무시되었거나 모델이 reasoning trace만 반환한 상태일 수 있습니다."
            )

        if done_reason == "length":
            return (
                "EMPTY_REPLY_LENGTH_WITHOUT_CONTENT: "
                "응답이 길이 제한에서 종료되었지만 content가 비어 있습니다."
            )

        if done_reason == "stop":
            return (
                "EMPTY_REPLY_STOPPED_WITHOUT_CONTENT: "
                "모델이 stop으로 종료되었지만 content가 비어 있습니다."
            )

        return (
            "EMPTY_REPLY_UNKNOWN: "
            "최종 답변(content)이 비어 있습니다. 원인을 단정할 수 없어 raw 응답 요약을 함께 확인해야 합니다."
        )

    def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        require_complete: bool = False,
        truncated_notice: str | None = DEFAULT_TRUNCATED_NOTICE,
    ) -> str:
        model_name = (model or self.model).strip()
        payload = self._build_payload(messages, model_name=model_name)

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )

        if resp.status_code >= 400:
            raise RuntimeError(f"Ollama error {resp.status_code}: {resp.text}")

        data = resp.json()
        message = data.get("message") or {}
        content = (message.get("content") or "").strip()
        done_reason = str(data.get("done_reason") or "").strip().lower()

        if content:
            if done_reason == "length":
                summary = self._summarize_response(data)
                if require_complete:
                    raise RuntimeError(f"TRUNCATED_REPLY_LENGTH | summary={summary}")
                if truncated_notice:
                    return content + truncated_notice
            return content

        classification = self._classify_empty_reply(data)
        summary = self._summarize_response(data)

        raise RuntimeError(f"{classification} | summary={summary}")

    @classmethod
    def list_local_models(
        cls,
        base_url: str = OLLAMA_BASE_URL,
        timeout: int = 10,
    ) -> list[dict]:
        resp = requests.get(
            f"{base_url.rstrip('/')}/api/tags",
            timeout=timeout,
        )

        if resp.status_code >= 400:
            raise RuntimeError(f"Ollama tags error {resp.status_code}: {resp.text}")

        data = resp.json()
        models = data.get("models") or []

        result: list[dict] = []
        seen: set[str] = set()

        for item in models:
            name = str(item.get("name") or item.get("model") or "").strip()
            if not name or name in seen:
                continue

            seen.add(name)

            details = item.get("details") or {}
            result.append(
                {
                    "name": name,
                    "model": str(item.get("model") or name),
                    "size": item.get("size"),
                    "modified_at": item.get("modified_at"),
                    "parameter_size": details.get("parameter_size"),
                    "quantization_level": details.get("quantization_level"),
                    "family": details.get("family"),
                }
            )

        result.sort(key=lambda x: x["name"].lower())
        return result

    @classmethod
    def list_local_model_names(
        cls,
        base_url: str = OLLAMA_BASE_URL,
        timeout: int = 10,
    ) -> list[str]:
        return [item["name"] for item in cls.list_local_models(base_url=base_url, timeout=timeout)]
