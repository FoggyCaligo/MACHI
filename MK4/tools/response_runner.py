from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from tools.ollama_client import OllamaClient


@dataclass
class ResponseRunResult:
    text: str
    truncated: bool
    continuation_count: int
    message: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None


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
    def _trim_ellipsis(text: str) -> str:
        stripped = (text or "").rstrip()
        while stripped.endswith("...") or stripped.endswith("…"):
            if stripped.endswith("..."):
                stripped = stripped[:-3].rstrip()
            elif stripped.endswith("…"):
                stripped = stripped[:-1].rstrip()
        return stripped

    @staticmethod
    def _find_last_boundary(text: str) -> int:
        s = (text or "").rstrip()
        if not s:
            return -1

        boundaries = []
        for token in (".", "!", "?", "\n"):
            idx = s.rfind(token)
            if idx != -1:
                boundaries.append(idx)

        return max(boundaries) if boundaries else -1

    @classmethod
    def _extract_continuation_context(
        cls,
        text: str,
        *,
        max_completed_chars: int = 420,
        max_tail_chars: int = 180,
    ) -> tuple[str, str]:
        s = (text or "").strip()
        if not s:
            return "", ""

        boundary = cls._find_last_boundary(s)
        if boundary == -1:
            completed = ""
            tail = s[-max_tail_chars:]
        else:
            completed = s[: boundary + 1].strip()
            tail = s[boundary + 1 :].strip()

        if len(completed) > max_completed_chars:
            completed = completed[-max_completed_chars:].lstrip()

        if len(tail) > max_tail_chars:
            tail = tail[-max_tail_chars:].lstrip()

        return completed, tail

    @classmethod
    def _build_continuation_prompt(
        cls,
        text: str,
        fallback_prompt: str | None = None,
    ) -> str:
        completed, tail = cls._extract_continuation_context(text)

        if fallback_prompt:
            base_instruction = fallback_prompt.strip()
        else:
            base_instruction = (
                "직전 assistant 답변은 이미 사용자에게 보여졌습니다. "
                "반복하거나 다시 요약하지 말고, 마지막 지점 바로 다음부터만 이어 쓰세요. "
                "새로운 내용만 이어서 쓰고, 완결된 문장으로 마무리하세요."
            )

        parts = [base_instruction]
        if completed:
            parts.append(f"이미 말한 마지막 완결 구간:{completed}")
        if tail:
            parts.append(f"직전 답변의 마지막 꼬리:{tail}")
        parts.append(
            "규칙:\n- 위 내용을 다시 반복하지 마세요.\n- 꼬리가 있다면 그 바로 다음부터만 이어 쓰세요.\n- 예시 문장, 괄호 설명, 안내문을 출력하지 마세요.\n- 새로운 내용만 이어서 쓰고, 완결된 문장으로 끝내세요."
        )
        return "".join(parts)


    def run(
        self,
        messages: list[dict],
        model: str | None = None,
        continuation_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ResponseRunResult:

        result = self.client.chat_with_metadata(
            messages,
            model=model,
            require_complete=False,
            truncated_notice=None,
            tools=tools,
        )
        text = str(result.get("raw_content") or result.get("content") or "").strip()
        truncated = bool(result.get("truncated"))
        tool_calls = result.get("tool_calls") or []
        message = result.get("message")
        if tool_calls:
            return ResponseRunResult(
                text=text,
                truncated=truncated,
                continuation_count=0,
                message=message,
                tool_calls=tool_calls,
            )
        count = 0

        while count < self.max_continuations and text and truncated:
            
            resolved_continuation_prompt = self._build_continuation_prompt(
                text=text,
                fallback_prompt=continuation_prompt,
            )

            continuation_messages = list(messages) + [
                {'role': 'assistant', 'content': text},
                {'role': 'user', 'content': resolved_continuation_prompt},
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

            next_text = str(next_result.get("raw_content") or next_result.get("content") or "").strip()
            if not next_text:
                break

            trimmed_text = self._trim_ellipsis(text)

            # 언어 특화 휴리스틱 대신, 실제 중복/반복만 억제
            if self._tail_similarity(trimmed_text, next_text) >= 0.72:
                break

            merged = self._merge_without_overlap(trimmed_text, next_text)
            if merged == trimmed_text:
                break

            text = merged
            truncated = bool(next_result.get("truncated"))
            count += 1

        return ResponseRunResult(
            text=text,
            truncated=truncated,
            continuation_count=count,
            message=message if isinstance(message, dict) else None,
            tool_calls=[],
        )
