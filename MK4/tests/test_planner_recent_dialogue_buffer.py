from __future__ import annotations

from MK4.app.pipeline import Pipeline


def test_planner_dialogue_buffer_keeps_latest_four_pairs_per_session() -> None:
    pipeline = object.__new__(Pipeline)
    pipeline._planner_recent_dialogue_pairs = {}

    for index in range(6):
        pipeline._remember_planner_dialogue_pair(
            conversation_key="user::session-a",
            user_message=f"user-{index}",
            assistant_message=f"assistant-{index}",
        )

    pipeline._remember_planner_dialogue_pair(
        conversation_key="user::session-b",
        user_message="other-user",
        assistant_message="other-assistant",
    )

    assert pipeline._planner_recent_dialogue_pairs["user::session-a"] == [
        {"user": "user-2", "assistant": "assistant-2"},
        {"user": "user-3", "assistant": "assistant-3"},
        {"user": "user-4", "assistant": "assistant-4"},
        {"user": "user-5", "assistant": "assistant-5"},
    ]
    assert pipeline._planner_recent_dialogue_pairs["user::session-b"] == [
        {"user": "other-user", "assistant": "other-assistant"},
    ]
