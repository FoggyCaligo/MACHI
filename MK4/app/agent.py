from config import (
    GENERAL_REPLY_MAX_CONTINUATIONS,
    GENERAL_REPLY_NUM_PREDICT,
    GENERAL_REPLY_TIMEOUT,
)
from prompts.response_builder import build_messages
from tools.ollama_client import OllamaClient


class Agent:
    def __init__(self) -> None:
        self.client = OllamaClient(timeout=GENERAL_REPLY_TIMEOUT, num_predict=GENERAL_REPLY_NUM_PREDICT)

    def _needs_continuation(self, result: dict) -> bool:
        if bool(result.get("truncated")):
            return True

        text = str(result.get("raw_content") or result.get("content") or "").strip()
        if len(text) < 80:
            return False

        return text.endswith("...") or text.endswith("…")

    def respond(self, user_message: str, context: dict, model: str | None = None) -> str:
        messages = build_messages(user_message=user_message, context=context)
        result = self.client.chat_with_metadata(
            messages,
            model=model,
            require_complete=False,
            truncated_notice=None,
        )

        parts: list[str] = [str(result.get("raw_content") or result.get("content") or "").strip()]
        current_result = result

        for _ in range(GENERAL_REPLY_MAX_CONTINUATIONS):
            if not self._needs_continuation(current_result):
                break

            continuation_messages = list(messages) + [
                {"role": "assistant", "content": "\n\n".join(part for part in parts if part).strip()},
                {
                    "role": "user",
                    "content": "이어서 계속해 주세요. 이미 말한 내용은 반복하지 말고, 남은 핵심만 자연스럽게 이어서 마무리해 주세요.",
                },
            ]

            current_result = self.client.chat_with_metadata(
                continuation_messages,
                model=model,
                require_complete=False,
                truncated_notice=None,
            )
            next_text = str(current_result.get("raw_content") or current_result.get("content") or "").strip()
            if not next_text:
                break
            parts.append(next_text)

        return "\n\n".join(part for part in parts if part).strip()
