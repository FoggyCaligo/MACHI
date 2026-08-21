from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from .llm_client import ChatModel, ModelTurn
from .memory_context import (
    get_writable_terms,
    has_successful_memory_mutation,
    is_memory_commit_active,
    reset_memory_commit_active,
    set_memory_commit_active,
    set_memory_draft_answer,
)
from .tool_runtime import ToolDefinition, ToolRegistry


_MEMORY_TOOLS = {"write_memory", "revise_memory", "finish_memory_commit"}
_NON_REVIEW_TOOLS = {
    "graph_search",
    "tool_manual",
    "file_text_activation",
    "execution_guard",
    "write_memory",
    "revise_memory",
    "finish_memory_commit",
}


@dataclass
class TurnCycleState:
    draft_answer: str | None = None
    final_answer_kind: str = "answer"
    completion_tools: list[str] = field(default_factory=list)
    draft_history_len: int = 0
    draft_returned: bool = False
    commit_token: Token[bool] | None = None


_turn_cycle_state: ContextVar[TurnCycleState | None] = ContextVar("turn_cycle_state", default=None)


def set_turn_cycle_state() -> Token[TurnCycleState | None]:
    return _turn_cycle_state.set(TurnCycleState())


def reset_turn_cycle_state(token: Token[TurnCycleState | None]) -> None:
    state = _turn_cycle_state.get()
    if state is not None:
        _close_memory_commit(state)
    _turn_cycle_state.reset(token)


def _get_turn_cycle_state() -> TurnCycleState:
    state = _turn_cycle_state.get()
    if state is None:
        state = TurnCycleState()
        _turn_cycle_state.set(state)
    return state


@dataclass(slots=True)
class TurnCycleChatModel:
    inner: ChatModel

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
        state = _get_turn_cycle_state()

        if state.draft_answer is not None:
            finish_index = _successful_tool_index_after(
                tool_history,
                "finish_memory_commit",
                state.draft_history_len,
            )
            if finish_index is not None and has_successful_memory_mutation():
                if state.draft_returned and _has_execution_guard_after(tool_history, finish_index):
                    _clear_draft(state)
                else:
                    _close_memory_commit(state)
                    state.draft_returned = True
                    return ModelTurn(
                        final_answer=state.draft_answer,
                        final_answer_kind=state.final_answer_kind,
                        completion_tools=list(state.completion_tools),
                    )
            else:
                return await self._memory_turn(
                    system=system,
                    user_message=user_message,
                    model=model,
                    memory_summary=memory_summary,
                    tool_definitions=tool_definitions,
                    tool_history=tool_history,
                )

        recall_index = _first_successful_tool_index(tool_history, "graph_search")
        if recall_index is None:
            recall_tools = [definition for definition in tool_definitions if definition.name == "graph_search"]
            if not recall_tools:
                raise RuntimeError("required recall_memory tool is not exposed")
            turn = await self.inner.next_turn(
                system=(
                    system
                    + "\nTurn phase: recall. Before any answer or other model-selected tool use, call recall_memory once. "
                    "The first recall is intentionally one-hop; use more recall calls later if needed."
                ),
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=recall_tools,
                tool_history=tool_history,
            )
            if any(call.tool == "graph_search" for call in turn.tool_calls):
                return turn
            raise RuntimeError("required recall phase was not completed: call recall_memory before answering")

        normal_tools = [definition for definition in tool_definitions if definition.name not in _MEMORY_TOOLS]
        reviewed = _tool_reviewed_after(tool_history, recall_index)
        if not reviewed:
            turn = await self.inner.next_turn(
                system=(
                    system
                    + "\nTurn phase: tool review. Inspect the exposed non-memory tools once before drafting the answer. "
                    "Use any needed tools. If none are needed, call skip_tool_use. Additional recall_memory calls are allowed."
                ),
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=normal_tools,
                tool_history=tool_history,
            )
            if turn.tool_calls:
                return turn
            raise RuntimeError(
                "required tool-review phase was not completed: use an appropriate tool or call skip_tool_use"
            )

        turn = await self.inner.next_turn(
            system=(
                system
                + "\nTurn phase: answer drafting. Memory mutation is not available yet. "
                "Use more recall or general tools if needed; otherwise produce the final answer draft."
            ),
            user_message=user_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=normal_tools,
            tool_history=tool_history,
        )
        if turn.final_answer and not turn.tool_calls:
            state.draft_answer = turn.final_answer
            state.final_answer_kind = turn.final_answer_kind
            state.completion_tools = list(turn.completion_tools)
            state.draft_history_len = len(tool_history)
            state.draft_returned = False
            set_memory_draft_answer(turn.final_answer)
            state.commit_token = set_memory_commit_active(True)
            return await self._memory_turn(
                system=system,
                user_message=user_message,
                model=model,
                memory_summary=memory_summary,
                tool_definitions=tool_definitions,
                tool_history=tool_history,
            )
        return turn

    async def _memory_turn(
        self,
        *,
        system: str,
        user_message: str,
        model: str | None,
        memory_summary: list[Any],
        tool_definitions: list[ToolDefinition],
        tool_history: list[dict[str, Any]],
    ) -> ModelTurn:
        if not is_memory_commit_active():
            raise RuntimeError("memory commit phase is not active")
        memory_tools = [
            definition
            for definition in tool_definitions
            if definition.name in _MEMORY_TOOLS or definition.name == "tool_manual"
        ]
        if not any(definition.name in {"write_memory", "revise_memory"} for definition in memory_tools):
            raise RuntimeError("memory commit tools are not exposed")
        writable_terms = get_writable_terms()
        commit_message = (
            user_message
            + "\n\nMemory commit context:\n"
            + "The user-visible answer draft is already fixed. New semantic nodes may use only term_id values "
            + "from writable_terms. Existing node_id values must have been returned by recall_memory or created "
            + "during this memory commit. Relations may be freely chosen between in-scope nodes. You may make "
            + "multiple chained graph mutations. Call finish_memory_commit only after at least one successful "
            + "write_memory or revise_memory mutation.\n"
            + f"writable_terms={writable_terms!r}"
        )
        turn = await self.inner.next_turn(
            system=(
                system
                + "\nTurn phase: memory commit. Do not rewrite the answer. "
                "Use write_memory/revise_memory to reflect this turn in the scoped graph, then finish_memory_commit."
            ),
            user_message=commit_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=memory_tools,
            tool_history=tool_history,
        )
        if turn.tool_calls:
            return turn
        raise RuntimeError("memory commit phase requires graph mutation tools or finish_memory_commit")


class TurnCycleToolSuite:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="skip_tool_use",
                description="Mark the mandatory tool-review phase complete when no non-memory tool is needed.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            self._skip_tool_use,
        )
        registry.register(
            ToolDefinition(
                name="finish_memory_commit",
                description="Finish the memory-commit phase after at least one graph mutation has succeeded.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            self._finish_memory_commit,
        )
        return registry

    async def _skip_tool_use(self, arguments: dict) -> dict:
        return {"ok": True, "reviewed": True}

    async def _finish_memory_commit(self, arguments: dict) -> dict:
        if not is_memory_commit_active():
            return {"ok": False, "error": "memory_commit_not_active"}
        if not has_successful_memory_mutation():
            return {
                "ok": False,
                "error": "memory_mutation_required",
                "message": "At least one write_memory or revise_memory mutation must succeed first.",
            }
        return {"ok": True, "finished": True}


def _close_memory_commit(state: TurnCycleState) -> None:
    if state.commit_token is not None:
        reset_memory_commit_active(state.commit_token)
        state.commit_token = None


def _clear_draft(state: TurnCycleState) -> None:
    _close_memory_commit(state)
    state.draft_answer = None
    state.final_answer_kind = "answer"
    state.completion_tools = []
    state.draft_history_len = 0
    state.draft_returned = False


def _first_successful_tool_index(tool_history: list[dict[str, Any]], tool_name: str) -> int | None:
    return _successful_tool_index_after(tool_history, tool_name, 0)


def _successful_tool_index_after(
    tool_history: list[dict[str, Any]],
    tool_name: str,
    start_index: int,
) -> int | None:
    for index, event in enumerate(tool_history[start_index:], start=start_index):
        if event.get("tool") != tool_name:
            continue
        result = event.get("result")
        if not isinstance(result, dict) or result.get("ok") is not False:
            return index
    return None


def _has_execution_guard_after(tool_history: list[dict[str, Any]], start_index: int) -> bool:
    return any(event.get("tool") == "execution_guard" for event in tool_history[start_index + 1:])


def _tool_reviewed_after(tool_history: list[dict[str, Any]], recall_index: int) -> bool:
    for event in tool_history[recall_index + 1:]:
        tool = str(event.get("tool") or "")
        if tool == "skip_tool_use":
            result = event.get("result")
            if isinstance(result, dict) and result.get("ok") is True:
                return True
            continue
        if tool and tool not in _NON_REVIEW_TOOLS:
            return True
    return False
