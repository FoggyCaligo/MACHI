from __future__ import annotations

from MK4.core.agent.file_completion import (
    file_mutation_completion_guard_result,
    requires_file_mutation,
)


def event(tool: str, *, path: str = "MK4/app/static/index.html", ok: bool = True) -> dict:
    return {
        "tool": tool,
        "arguments": {"path": path},
        "result": {"ok": ok, "path": path},
    }


def test_korean_file_edit_request_is_detected() -> None:
    assert requires_file_mutation('index.html에서 "새 채팅" 버튼을 없애줘') is True
    assert requires_file_mutation('MK4의 UI 코드를 수정해줘') is True
    assert requires_file_mutation('index.html을 읽고 구조를 설명해줘') is False


def test_final_answer_after_only_file_read_is_rejected() -> None:
    guard = file_mutation_completion_guard_result(
        user_message='index.html에서 새 채팅 버튼을 제거해줘',
        tool_history=[event('file_read')],
        rejected_final_answer='제거했습니다.',
    )
    assert guard is not None
    assert guard['error'] == 'requested_file_mutation_not_performed'


def test_plan_only_final_answer_is_rejected_before_mutation() -> None:
    guard = file_mutation_completion_guard_result(
        user_message='HTML 코드를 수정해줘',
        tool_history=[event('file_read')],
        rejected_final_answer='이제 해당 부분을 수정하겠습니다.',
    )
    assert guard is not None
    assert guard['error'] == 'requested_file_mutation_not_performed'


def test_successful_update_without_post_read_is_rejected() -> None:
    guard = file_mutation_completion_guard_result(
        user_message='HTML 파일을 수정해줘',
        tool_history=[event('file_read'), event('file_update')],
        rejected_final_answer='수정했습니다.',
    )
    assert guard is not None
    assert guard['error'] == 'requested_file_mutation_not_verified'


def test_successful_update_then_same_file_read_allows_completion() -> None:
    history = [event('file_read'), event('file_update'), event('file_read')]
    guard = file_mutation_completion_guard_result(
        user_message='HTML 파일을 수정해줘',
        tool_history=history,
        rejected_final_answer='수정했습니다.',
    )
    assert guard is None


def test_read_of_other_file_does_not_verify_mutation() -> None:
    history = [
        event('file_update', path='MK4/app/static/index.html'),
        event('file_read', path='MK4/README.md'),
    ]
    guard = file_mutation_completion_guard_result(
        user_message='HTML 파일을 수정해줘',
        tool_history=history,
        rejected_final_answer='수정했습니다.',
    )
    assert guard is not None
    assert guard['error'] == 'requested_file_mutation_not_verified'


def test_successful_delete_allows_completion_without_file_read() -> None:
    guard = file_mutation_completion_guard_result(
        user_message='이 파일을 삭제해줘',
        tool_history=[event('file_delete')],
        rejected_final_answer='삭제했습니다.',
    )
    assert guard is None
