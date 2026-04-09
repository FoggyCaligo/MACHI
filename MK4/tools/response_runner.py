from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
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
    def _tail_similarity(a: str, b: str, window: int = 320) -> float:
        a_tail = (a or "").strip()[-window:]
        b_text = (b or "").strip()
        if not a_tail or not b_text:
            return 0.0
        return SequenceMatcher(None, a_tail, b_text).ratio()

    @staticmethod
    def _looks_meta_continuation(text: str) -> bool:
        stripped = " ".join((text or "").strip().split())
        bad_prefixes = (
            "네, 계속하겠습니다",
            "이어서 말씀드리겠습니다",
            "계속해서 설명하겠습니다",
            "앞서 말씀드린",
        )
        return any(stripped.startswith(prefix) for prefix in bad_prefixes)

    @staticmethod
    def _merge_without_overlap(prev: str, new: str, max_overlap: int = 160) -> str:
        prev = (prev or "").rstrip()
        new = (new or "").strip()
        if not prev:
            return new
        if not new:
            return prev

        max_len = min(len(prev), len(new), max_overlap)
        overlap = 0
        for size in range(max_len, 19, -1):
            if prev[-size:] == new[:size]:
                overlap = size
                break

        if overlap:
            new = new[overlap:].lstrip()

        if not new:
            return prev

        return (prev + "\n\n" + new).strip()

    @staticmethod
    def _looks_incomplete(text: str) -> bool:
        stripped = (text or '').rstrip()
        if not stripped:
            return False
        if stripped.endswith('...') or stripped.endswith('…'):
            return True
        incomplete_endings = (
            '라는 것을', '것을', '때문에', '그래서', '다만', '하지만', '즉', '그리고',
            '있습니다만', '있는데', '있어', '같습니', '같아', '입니다만', '인데',
            '것 같', '보입니다만', '의미하', '말하자면',
        )
        return any(stripped.endswith(token) for token in incomplete_endings)

    @staticmethod
    def _trim_ellipsis(text: str) -> str:
        stripped = (text or '').rstrip()
        while stripped.endswith('...') or stripped.endswith('…'):
            if stripped.endswith('...'):
                stripped = stripped[:-3].rstrip()
            elif stripped.endswith('…'):
                stripped = stripped[:-1].rstrip()
        return stripped

    def run(
        self,
        messages: list[dict],
        model: str | None = None,
        continuation_prompt: str | None = None,
    ) -> ResponseRunResult:
        continuation_prompt = continuation_prompt or (
            "직전 답변의 마지막 문장 바로 다음부터 이어서 쓰세요. "
            "이미 쓴 문장을 반복하거나 요약하지 마세요. "
            "\"네, 계속하겠습니다\" 같은 메타 문장을 쓰지 마세요. "
            "새로운 내용만 1~3문장으로 이어 쓰고, 줄임표 없이 완결된 문장으로 끝내세요."
        )
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

            trimmed_text = self._trim_ellipsis(text)
            if self._looks_meta_continuation(next_text):
                break
            if self._tail_similarity(trimmed_text, next_text) >= 0.72:
                break
            merged = self._merge_without_overlap(trimmed_text, next_text)
            if merged == trimmed_text:
                break
            text = merged
            truncated = bool(next_result.get('truncated'))
            count += 1

        return ResponseRunResult(text=text, truncated=truncated, continuation_count=count)
