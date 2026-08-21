from __future__ import annotations

import pytest

from MK4.core.agent.orchestrator import _file_execution_guard_result
from MK4.tools.terminal_tools import TerminalToolSuite


def _terminal_event(
    *,
    changed: bool,
    changes_state: bool = False,
    verification: bool = False,
    ok: bool = True,
) -> dict:
    return {
        "tool": "terminal_command",
        "arguments": {
            "command": "check" if verification else "change",
            "changes_state": changes_state,
            "verification": verification,
        },
        "result": {
            "ok": ok,
            "returncode": 0 if ok else 1,
            "changes_state": changes_state,
            "verification": verification,
            "filesystem_changed": changed,
            "changed_paths": ["changed.txt"] if changed else [],
        },
    }


def test_terminal_filesystem_change_requires_verification() -> None:
    guard = _file_execution_guard_result(
        tool_history=[_terminal_event(changed=True)],
        rejected_final_answer="done",
    )

    assert guard is not None
    assert guard["error"] == "terminal_change_not_verified"


def test_declared_external_state_change_requires_verification() -> None:
    guard = _file_execution_guard_result(
        tool_history=[_terminal_event(changed=False, changes_state=True)],
        rejected_final_answer="done",
    )

    assert guard is not None
    assert guard["error"] == "terminal_change_not_verified"


def test_read_only_terminal_verification_satisfies_guard() -> None:
    guard = _file_execution_guard_result(
        tool_history=[
            _terminal_event(changed=False, changes_state=True),
            _terminal_event(changed=False, verification=True),
        ],
        rejected_final_answer="done",
    )

    assert guard is None


def test_mutating_terminal_verification_does_not_satisfy_guard() -> None:
    guard = _file_execution_guard_result(
        tool_history=[
            _terminal_event(changed=True),
            _terminal_event(changed=True, verification=True),
        ],
        rejected_final_answer="done",
    )

    assert guard is not None
    assert guard["error"] == "terminal_change_not_verified"


def test_failed_terminal_verification_does_not_satisfy_guard() -> None:
    guard = _file_execution_guard_result(
        tool_history=[
            _terminal_event(changed=True),
            _terminal_event(changed=False, verification=True, ok=False),
        ],
        rejected_final_answer="done",
    )

    assert guard is not None
    assert guard["error"] == "terminal_change_not_verified"


def test_terminal_command_exposes_structured_change_and_verification_flags() -> None:
    definition = next(
        item
        for item in TerminalToolSuite().build_registry().definitions()
        if item.name == "terminal_command"
    )

    properties = definition.input_schema["properties"]
    assert properties["changes_state"]["type"] == "boolean"
    assert properties["preconditions_verified"]["type"] == "boolean"
    assert properties["verification"]["type"] == "boolean"


@pytest.mark.asyncio
async def test_terminal_rejects_string_boolean_instead_of_silently_coercing() -> None:
    suite = TerminalToolSuite()

    with pytest.raises(ValueError, match="changes_state must be a JSON boolean"):
        await suite._run({"command": "echo test", "changes_state": "True"})


@pytest.mark.asyncio
async def test_terminal_state_change_requires_verified_preconditions() -> None:
    suite = TerminalToolSuite()

    with pytest.raises(ValueError, match="state changes require preconditions_verified=true"):
        await suite._run({"command": "echo test", "changes_state": True})


@pytest.mark.asyncio
async def test_preconditions_verified_is_only_valid_for_state_change() -> None:
    suite = TerminalToolSuite()

    with pytest.raises(ValueError, match="only valid with changes_state=true"):
        await suite._run({"command": "echo test", "preconditions_verified": True})
