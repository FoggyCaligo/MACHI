from __future__ import annotations

import pytest

from MK4.tools.tool_runtime import (
    ToolCall,
    ToolDefinition,
    ToolRegistry,
    reset_file_task_message,
    set_file_task_message,
)


def _definition(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=name, input_schema={"type": "object"})


@pytest.mark.asyncio
async def test_style_to_script_swap_is_blocked_before_handler_runs() -> None:
    registry = ToolRegistry()
    called = False

    async def update(arguments: dict) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    registry.register(_definition("file_update"), update)
    tokens = set_file_task_message(
        "MK4의 UI에서 이미지 인식 모델을 선택하는 select를 없애고 관련 JS만 정리해줘."
    )
    try:
        result = await registry.run(
            ToolCall(
                tool="file_update",
                arguments={
                    "path": "MK4/app/static/index.html",
                    "old": "</style>\n</head>\n<body>",
                    "new": "</script>\n</head>\n<body>",
                },
            )
        )
    finally:
        reset_file_task_message(tokens)

    assert called is False
    assert result["ok"] is False
    assert result["error"] == "file_update_unrelated_structure_change"


@pytest.mark.asyncio
async def test_small_requested_select_removal_is_allowed() -> None:
    registry = ToolRegistry()
    called = False

    async def update(arguments: dict) -> dict:
        nonlocal called
        called = True
        return {"ok": True, "path": arguments["path"], "status": "updated"}

    registry.register(_definition("file_update"), update)
    tokens = set_file_task_message(
        "Machi 레포의 MK4에서 image-model-select를 제거하고 그 참조 코드만 정리해줘."
    )
    try:
        result = await registry.run(
            ToolCall(
                tool="file_update",
                arguments={
                    "path": "MK4/app/static/index.html",
                    "old": '<select id="image-model-select" title="이미지 인식 모델 선택">\n  <option>...</option>\n</select>',
                    "new": "",
                },
            )
        )
    finally:
        reset_file_task_message(tokens)

    assert called is True
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_local_request_cannot_full_overwrite_file() -> None:
    registry = ToolRegistry()
    called = False

    async def update(arguments: dict) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    registry.register(_definition("file_update"), update)
    tokens = set_file_task_message("새 채팅 버튼만 제거해줘. 다른 UI는 건드리지 마.")
    try:
        result = await registry.run(
            ToolCall(
                tool="file_update",
                arguments={"path": "MK4/app/static/index.html", "content": "<html>rewritten</html>"},
            )
        )
    finally:
        reset_file_task_message(tokens)

    assert called is False
    assert result["error"] == "file_update_scope_too_broad"


@pytest.mark.asyncio
async def test_large_local_replacement_is_blocked() -> None:
    registry = ToolRegistry()
    called = False

    async def update(arguments: dict) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    registry.register(_definition("file_update"), update)
    old = "\n".join(f"line {i}" for i in range(100))
    new = old.replace("line 50", "button removed")
    tokens = set_file_task_message("새 채팅 버튼만 제거해줘.")
    try:
        result = await registry.run(
            ToolCall(
                tool="file_update",
                arguments={"path": "MK4/app/static/index.html", "old": old, "new": new},
            )
        )
    finally:
        reset_file_task_message(tokens)

    assert called is False
    assert result["error"] == "file_update_scope_too_broad"


@pytest.mark.asyncio
async def test_project_names_are_not_treated_as_required_code_anchors() -> None:
    registry = ToolRegistry()
    called = False

    async def update(arguments: dict) -> dict:
        nonlocal called
        called = True
        return {"ok": True, "path": arguments["path"]}

    registry.register(_definition("file_update"), update)
    tokens = set_file_task_message(
        "현재 레포가 Machi이고 MK4 폴더가 프로젝트야. 이미지 인식 모델 select를 제거해줘."
    )
    try:
        result = await registry.run(
            ToolCall(
                tool="file_update",
                arguments={
                    "path": "MK4/app/static/index.html",
                    "old": '<select title="이미지 인식 모델 선택">x</select>',
                    "new": "",
                },
            )
        )
    finally:
        reset_file_task_message(tokens)

    assert called is True
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_explicit_identifier_must_appear_in_local_change() -> None:
    registry = ToolRegistry()
    called = False

    async def update(arguments: dict) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    registry.register(_definition("file_update"), update)
    tokens = set_file_task_message("`image-model-select`만 제거해줘.")
    try:
        result = await registry.run(
            ToolCall(
                tool="file_update",
                arguments={
                    "path": "MK4/app/static/index.html",
                    "old": '<button id="logout-btn">logout</button>',
                    "new": "",
                },
            )
        )
    finally:
        reset_file_task_message(tokens)

    assert called is False
    assert result["error"] == "file_update_missing_request_anchor"
