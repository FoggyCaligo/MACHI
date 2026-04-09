from __future__ import annotations

import re

MEMORY_REFERENCE_PATTERNS = (
    "이전에 내가 준", "예전에 내가 준", "전에 내가 준", "이전에 준",
    "블로그 글", "그 글", "그 파일", "그 텍스트", "첫번째 글", "첫 번째 글",
    "기억하고 있", "기억하니", "기억해", "기억나", "기억 안",
    "remember",
)

ANALYSIS_REFERENCE_PATTERNS = (
    "그 글들의", "그 글들", "그 파일", "그 텍스트", "그 내용",
    "화자", "특징", "무슨 글", "첫번째 글", "첫 번째 글",
)


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().split())


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(p.lower() in lowered for p in patterns)


def maybe_build_direct_reply(user_message: str, context: dict | None = None) -> str | None:
    text = _normalize(user_message)
    if not text:
        return None

    context = context or {}
    has_direct_source = bool(context.get("source_contents") or context.get("attached_text") or context.get("project_chunks"))
    if has_direct_source:
        return None

    asks_memory = _contains_any(text, MEMORY_REFERENCE_PATTERNS)
    asks_analysis_without_source = _contains_any(text, ANALYSIS_REFERENCE_PATTERNS) and ("특징" in text or "화자" in text or "말해" in text or "무엇" in text)

    if asks_memory:
        return (
            "지금 이 대화 기준으로는, 예전에 주셨던 블로그 글의 구체적인 원문이나 순서를 기억하고 있다고 말할 수 없습니다. "
            "현재 대화에 그 글의 내용이 다시 들어오지 않았기 때문입니다. 파일이나 텍스트를 다시 주시면, 그걸 기준으로 정확하게 읽고 답하겠습니다."
        )

    if asks_analysis_without_source:
        return (
            "지금 이 대화에는 그 글들의 실제 원문이 없어서, 화자의 특징을 근거 있게 말할 수 없습니다. "
            "파일이나 텍스트를 다시 주시면, 그 내용을 읽은 뒤 화자의 특징을 구조적으로 정리해드리겠습니다."
        )

    return None
