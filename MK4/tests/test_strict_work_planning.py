from __future__ import annotations

from typing import Any

import pytest

from MK4.tools.llm_client import ModelTurn
from MK4.tools.required_tool_model import _required_tool_response_schema
from MK4.tools.strict_work_planning import StrictWorkPlanningChatModel
from MK4.tools.tool_runtime import ToolCall, ToolDefinition
from MK4.tools.work_plan_tools import WorkPlanToolSuite


class NoopChatModel:
    async def next_turn(self, **_: Any) -> ModelTurn:
        return ModelTurn(final_answer="should only be used after plan completion")


class RecordingRequiredToolModel:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.required_tools: list[str] = []

    async def next_required_tool(self, *, required_tool: str, **_: Any) -> ModelTurn:
        self.required_tools.append(required_tool)
        return self.turns.pop(0)


def _definition(name: str, schema: dict[str, Any] | None = None) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        input_schema=schema or {"type": "object", "additionalProperties": True},
    )


def _manual_event(tool: str) -> dict[str, Any]:
    return {
        "tool": "tool_manual",
        "arguments": {"tool": tool},
        "result": {"ok": True, "tool": tool},
    }


def _plan_event(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tool": "work_plan",
        "arguments": {},
        "result": {"ok": True, "goal": "complete request", "steps": steps},
    }


def test_required_tool_schema_forbids_final_answer_and_other_tools() -> None:
    definition = _definition(
        "work_plan",
        {"type": "object", "properties": {"goal": {"type": "string"}}},
    )
    schema = _required_tool_response_schema(definition)

    assert schema["properties"]["final_answer"] == {"type": "null"}
    calls = schema["properties"]["tool_calls"]
    assert calls["minItems"] == 1
    assert calls["maxItems"] == 1
    item = calls["items"]
    assert item["properties"]["tool"]["enum"] == ["work_plan"]
    assert item["properties"]["arguments"] == definition.input_schema


def test_work_plan_schema_still_allows_reasoning_steps_without_tools() -> None:
    registry = WorkPlanToolSuite().build_registry()
    definition = registry.definition("work_plan")
    assert definition is not None

    step_schema = definition.input_schema["properties"]["steps"]["items"]
    assert step_schema["properties"]["action_type"]["enum"] == ["reasoning", "tool"]
    assert step_schema["properties"]["tool"]["type"] == ["string", "null"]


@pytest.mark.asyncio
async def test_plan_phase_uses_required_work_plan_contract_after_manual() -> None:
    plan_call = ToolCall(
        tool="work_plan",
        arguments={
            "goal": "remember user",
            "steps": [{
                "step_id": "s1",
                "claim": "organize recalled memories",
                "action_type": "reasoning",
                "tool": None,
                "depends_on": [],
            }],
        },
    )
    required = RecordingRequiredToolModel([ModelTurn(tool_calls=[plan_call])])
    model = StrictWorkPlanningChatModel(
        NoopChatModel(),
        required_tool_model=required,  # type: ignore[arg-type]
    )

    turn = await model.next_turn(
        system="system",
        user_message="나에 대해 기억하는 걸 말해봐",
        model=None,
        memory_summary=[],
        tool_definitions=[
            _definition("tool_manual"),
            WorkPlanToolSuite().build_registry().definition("work_plan"),  # type: ignore[list-item]
            WorkPlanToolSuite().build_registry().definition("work_step_complete"),  # type: ignore[list-item]
        ],
        tool_history=[_manual_event("work_plan")],
    )

    assert required.required_tools == ["work_plan"]
    assert turn.final_answer is None
    assert turn.tool_calls == [plan_call]


@pytest.mark.asyncio
async def test_reasoning_step_is_structurally_constrained_to_step_complete() -> None:
    steps = [{
        "step_id": "reason-1",
        "claim": "organize memories",
        "action_type": "reasoning",
        "tool": None,
        "depends_on": [],
    }]
    completion = ToolCall(
        tool="work_step_complete",
        arguments={"step_id": "reason-1", "conclusion": "organized"},
    )
    required = RecordingRequiredToolModel([ModelTurn(tool_calls=[completion])])
    model = StrictWorkPlanningChatModel(
        NoopChatModel(),
        required_tool_model=required,  # type: ignore[arg-type]
    )

    turn = await model.next_turn(
        system="system",
        user_message="question",
        model=None,
        memory_summary=[],
        tool_definitions=[
            _definition("tool_manual"),
            _definition("work_plan"),
            _definition("work_step_complete"),
        ],
        tool_history=[_plan_event(steps), _manual_event("work_step_complete")],
    )

    assert required.required_tools == ["work_step_complete"]
    assert turn.tool_calls == [completion]


@pytest.mark.asyncio
async def test_tool_step_is_structurally_constrained_to_planned_tool() -> None:
    steps = [{
        "step_id": "read-1",
        "claim": "read target file",
        "action_type": "tool",
        "tool": "file_read",
        "depends_on": [],
    }]
    call = ToolCall(tool="file_read", arguments={"path": "README.md"})
    required = RecordingRequiredToolModel([ModelTurn(tool_calls=[call])])
    model = StrictWorkPlanningChatModel(
        NoopChatModel(),
        required_tool_model=required,  # type: ignore[arg-type]
    )

    turn = await model.next_turn(
        system="system",
        user_message="read it",
        model=None,
        memory_summary=[],
        tool_definitions=[
            _definition("tool_manual"),
            _definition("work_plan"),
            _definition("work_step_complete"),
            _definition("file_read", {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            }),
        ],
        tool_history=[_plan_event(steps), _manual_event("file_read")],
    )

    assert required.required_tools == ["file_read"]
    assert turn.tool_calls == [call]
