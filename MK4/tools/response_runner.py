from __future__ import annotations

from dataclasses import dataclass

from tools.ollama_client import OllamaClient


@dataclass
class ResponseRunResult:
    text: str
    truncated: bool
    continuation_count: int


class ResponseRunner:
    def __init__(
        self,
        timeout: int,
        num_predict: int,
        max_continuations: int = 1,
    ) -> None:
        self.client = OllamaClient(timeout=timeout, num_predict=num_predict)
        self.max_continuations = max(0, int(max_continuations))

    @staticmethod
    def _looks_incomplete(text: str) -> bool:
        stripped = (text or '').rstrip()
        if not stripped:
            return False
        if stripped.endswith('...') or stripped.endswith('…'):
            return True
        incomplete_endings = (
            '라는 것을', '것을', '때문에', '그래서', '다만', '하지만', '즉', '그리고',
            '있습니다만', '있는데', '있어', '같습니', '같아',
        )
        return any(stripped.endswith(token) for token in incomplete_endings)

    def run(
        self,
        messages: list[dict],
        model: str | None = None,
        continuation_prompt: str | None = None,
    ) -> ResponseRunResult:
        continuation_prompt = continuation_prompt or '이어서 계속해 주세요. 이미 말한 내용은 반복하지 말고, 남은 핵심만 자연스럽게 마무리해 주세요.'

        result = self.client.chat_with_metadata(
            messages,
            model=model,
            require_complete=False,
            truncated_notice=None,
        )
        text = str(result.get('raw_content') or result.get('content') or '').strip()
        truncated = bool(result.get('truncated'))
        count = 0

        while count < self.max_continuations and text:
            if not truncated and not self._looks_incomplete(text):
                break

            continuation_messages = list(messages) + [
                {'role': 'assistant', 'content': text},
                {'role': 'user', 'content': continuation_prompt},
            ]

            try:
                next_result = self.client.chat_with_metadata(
                    continuation_messages,
                    model=model,
                    require_complete=False,
                    truncated_notice=None,
                )
            except RuntimeError:
                break

            next_text = str(next_result.get('raw_content') or next_result.get('content') or '').strip()
            if not next_text:
                break

            text = (text + "\n\n" + next_text).strip()
            truncated = bool(next_result.get('truncated'))
            count += 1

        return ResponseRunResult(text=text, truncated=truncated, continuation_count=count)
