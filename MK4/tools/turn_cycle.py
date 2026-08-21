from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .llm_client import ChatModel, ModelTurn
from .memory_context import get_writable_terms, is_memory_commit_active
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
        if is_memory_commit_active():
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
                    + "\nTurn phase: recall. Before any answer or other tool use, call recall_memory once. "
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

        return await self.inner.next_turn(
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
        memory_tools = [
            definition
            for definition in tool_definitions
            if definition.name in _MEMORY_TOOLS or definition.name == "tool_manual"
        ]
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
        return {"ok": True, "finished": True}


def _first_successful_tool_index(tool_history: list[dict[str, Any]], tool_name: str) -> int | None:
    for index, event in enumerate(tool_history):
        if event.get("tool") != tool_name:
            continue
        result = event.get("result")
        if not isinstance(result, dict) or result.get("ok") is not False:
            return index
    return None


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
