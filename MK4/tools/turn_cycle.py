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
from .tool_runtime import ToolCall, ToolDefinition, ToolRegistry


_MEMORY_TOOLS = {"write_memory", "revise_memory", "finish_memory_commit"}
_INTERNAL_PHASE_TOOL = "_begin_memory_commit"


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

        if _first_successful_tool_index(tool_history, "graph_search") is None:
            recall_tools = [definition for definition in tool_definitions if definition.name == "graph_search"]
            if not recall_tools:
                raise RuntimeError("required recall_memory tool is not exposed")
            turn = await self.inner.next_turn(
                system=(
                    system
                    + "\nTurn phase: recall. Before any answer or other model-selected tool use, call recall_memory once. "
                    "The first recall is intentionally one-hop; use more recall calls later if needed. "
                    "Choose exactly one compact agent action: tool."
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

        normal_tools = [
            definition
            for definition in tool_definitions
            if definition.name not in _MEMORY_TOOLS and definition.name != _INTERNAL_PHASE_TOOL
        ]
        turn = await self.inner.next_turn(
            system=(
                system
                + "\nTurn phase: tool review and answer drafting. Review the exposed non-memory tools before answering. "
                "Use any needed tool, including additional recall_memory. If no tool is needed, produce the final answer "
                "draft directly; choosing a final answer while tools are exposed is the explicit no-tool decision. "
                "Memory mutation is not available yet. Choose exactly one compact agent action: tool or answer."
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
            return ModelTurn(tool_calls=[ToolCall(tool=_INTERNAL_PHASE_TOOL, arguments={})])
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
        mutation_succeeded = has_successful_memory_mutation()
        allowed_memory_tools = {"write_memory", "revise_memory"}
        if mutation_succeeded:
            allowed_memory_tools.add("finish_memory_commit")
        memory_tools = [
            definition
            for definition in tool_definitions
            if definition.name in allowed_memory_tools or definition.name == "tool_manual"
        ]
        if not any(definition.name in {"write_memory", "revise_memory"} for definition in memory_tools):
            raise RuntimeError("memory commit tools are not exposed")
        writable_terms = get_writable_terms()
        completion_instruction = (
            "At least one memory mutation has already succeeded. You may continue mutating memory or choose done."
            if mutation_succeeded
            else "No memory mutation has succeeded yet. Choose write_memory or revise_memory; done is not available yet."
        )
        commit_message = (
            user_message
            + "\n\nMemory commit context:\n"
            + "The user-visible answer draft is already fixed. New semantic nodes may use only term_id values "
            + "from writable_terms. Existing node_id values must have been returned by recall_memory or created "
            + "during this memory commit. Relations may be freely chosen between in-scope nodes. You may make "
            + "multiple chained graph mutations. "
            + completion_instruction
            + "\n"
            + f"writable_terms={writable_terms!r}"
        )
        phase_action = "tool or done" if mutation_succeeded else "tool"
        turn = await self.inner.next_turn(
            system=(
                system
                + "\nTurn phase: memory commit. Do not rewrite the answer. "
                + completion_instruction
                + f" Choose exactly one compact agent action: {phase_action}."
            ),
            user_message=commit_message,
            model=model,
            memory_summary=memory_summary,
            tool_definitions=memory_tools,
            tool_history=tool_history,
        )
        if turn.tool_calls:
            return turn
        raise RuntimeError("memory commit phase requires one exposed memory action")


class TurnCycleToolSuite:
    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name=_INTERNAL_PHASE_TOOL,
                description="Internal framework transition into memory commit.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            self._begin_memory_commit,
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

    async def _begin_memory_commit(self, arguments: dict) -> dict:
        if not is_memory_commit_active():
            return {"ok": False, "error": "memory_commit_not_active"}
        return {"ok": True, "phase": "memory_commit"}

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
