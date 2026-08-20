from __future__ import annotations

from typing import Any

from .llm_client import ChatModel, ModelTurn
from .tool_runtime import ToolDefinition


_AUTONOMY_RETRY_INSTRUCTION = """
The previous answer tried to ask the user for a routine intermediate decision that should be resolved autonomously.
Do not ask the user for code, file paths, selectors, routine implementation choices, permission to inspect/search/read/test, or other discoverable details.
Use the available tools, inspect the surrounding context, choose the simplest safe and reversible implementation when several ordinary choices are possible, and continue toward the user's end goal.
Ask the user only when a genuinely missing preference would materially change the user-visible outcome, required information cannot be discovered with tools, or the next action is destructive, irreversible, security-sensitive, or externally impactful.
Return tool_calls when more work is needed; otherwise return the completed final answer.
""".strip()

_WORKSPACE_TOOL_NAMES = {
    "file_tree",
    "file_search",
    "file_text_search",
    "file_read",
    "file_update",
    "file_create",
    "code_index",
    "code_search",
    "terminal_command",
}

_ROUTINE_RESOURCE_HINTS = (
    "파일", "경로", "위치", "코드", "html", "css", "selector", "셀렉터", "클래스", "class",
    "함수", "function", "snippet", "스니펫", "file", "path", "source", "소스",
)

_ROUTINE_ACTION_HINTS = (
    "읽어볼까요", "찾아볼까요", "검색해볼까요", "확인해볼까요", "수정할까요", "테스트해볼까요",
    "진행할까요", "실행해볼까요", "검토할까요", "살펴볼까요", "보내주세요", "붙여넣어",
    "알려주세요", "제공해주", "복사해", "which file", "which path", "please provide", "please send",
    "paste the", "tell me the", "would you like me to", "should i search", "should i read", "should i inspect",
    "should i test", "should i proceed",
)

_PROTECTED_CLARIFICATION_HINTS = (
    "파일을 삭제", "폴더를 삭제", "레포를 삭제", "repository 삭제", "데이터베이스를 삭제",
    "배포", "deploy", "메일을 보내", "이메일을 보내", "메시지를 보내", "결제", "구매", "publish",
    "색상", "색깔", "디자인", "레이아웃", "문구", "스타일", "어느 쪽", "둘 중", "a/b",
)


class AutonomyChatModel:
    """Retry routine clarification answers before they reach the user."""

    def __init__(self, delegate: ChatModel, *, max_retries: int = 1) -> None:
        self._delegate = delegate
        self._max_retries = max(0, max_retries)

    async def next_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[Any],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        turn = await self._delegate.next_turn(
            system=system,
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=tool_definitions,
            tool_history=tool_history,
        )
        retries = 0
        while retries < self._max_retries and _should_retry_routine_clarification(
            turn,
            tool_definitions=tool_definitions,
        ):
            retries += 1
            rejected = turn.final_answer or ""
            retry_history = [
                *tool_history,
                {
                    "tool": "autonomy_guard",
                    "arguments": {},
                    "result": {
                        "ok": False,
                        "error": "routine_clarification_blocked",
                        "message": _AUTONOMY_RETRY_INSTRUCTION,
                        "rejected_final_answer": rejected[:1000],
                    },
                },
            ]
            turn = await self._delegate.next_turn(
                system=f"{system}\n{_AUTONOMY_RETRY_INSTRUCTION}",
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
                tool_history=retry_history,
            )
        return turn


def _should_retry_routine_clarification(
    turn: ModelTurn,
    *,
    tool_definitions: list[ToolDefinition],
) -> bool:
    if turn.tool_calls or not turn.final_answer or turn.final_answer_kind == "blocked":
        return False
    available = {definition.name for definition in tool_definitions}
    if not (available & _WORKSPACE_TOOL_NAMES):
        return False

    text = turn.final_answer.strip().lower()
    if not text:
        return False
    if any(hint in text for hint in _PROTECTED_CLARIFICATION_HINTS):
        return False

    asks_for_resource = any(hint in text for hint in _ROUTINE_RESOURCE_HINTS)
    asks_routine_action = any(hint in text for hint in _ROUTINE_ACTION_HINTS)
    looks_like_question = "?" in text or any(
        ending in text
        for ending in ("할까요", "인가요", "있나요", "주실 수", "주세요", "알려주", "보내주", "제공해")
    )
    return looks_like_question and (asks_for_resource or asks_routine_action)
