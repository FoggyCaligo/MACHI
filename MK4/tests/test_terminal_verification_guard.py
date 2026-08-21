from __future__ import annotations

from MK4.core.agent.orchestrator import _file_execution_guard_result
from MK4.tools.terminal_tools import TerminalToolSuite


def _terminal_event(*, changed: bool, verification: bool = False, ok: bool = True) -> dict:
    return {
        "tool": "terminal_command",
        "arguments": {
            "command": "check" if verification else "change",
            "verification": verification,
        },
        "result": {
            "ok": ok,
            "returncode": 0 if ok else 1,
            "verification": verification,
            "filesystem_changed": changed,
            "changed_paths": ["changed.txt"] if changed else [],
        },
    }


def test_terminal_change_requires_verification() -> None:
    guard = _file_execution_guard_result(
        tool_history=[_terminal_event(changed=True)],
        rejected_final_answer="done",
    )

    assert guard is not None
    assert guard["error"] == "terminal_change_not_verified"


def test_read_only_terminal_verification_satisfies_guard() -> None:
    guard = _file_execution_guard_result(
        tool_history=[
            _terminal_event(changed=True),
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


def test_terminal_command_exposes_structured_verification_flag() -> None:
    definition = next(
        item
        for item in TerminalToolSuite().build_registry().definitions()
        if item.name == "terminal_command"
    )

    verification = definition.input_schema["properties"]["verification"]
    assert verification["type"] == "boolean"
