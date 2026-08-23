from __future__ import annotations

import json

import pytest

from MK4.tools import grounding_tools
from MK4.tools.grounding_tools import review_final_grounding


@pytest.mark.asyncio
async def test_final_review_can_be_grounded_but_task_misaligned(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["system"] = system
        captured["payload"] = json.loads(user)
        captured["schema"] = response_format
        return json.dumps({
            "grounded": True,
            "task_aligned": False,
            "missing_aspects": [
                "The response explains feed and nib but does not answer the two feed structures or identify Preppy's structure."
            ],
        })

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_chat)
    review = await review_final_grounding(
        system="system",
        user_message=(
            "Previous dialogue turn:\n"
            "- User: 플래티넘 프레피에 대해 알고 싶어.\n"
            "- Assistant: 프레피를 설명함.\n\n"
            "Current user message:\n"
            "닙에 잉크를 공급하는 솜 같은 구조와 구조적으로 생긴 방식의 이름, 그리고 프레피가 어느 쪽인지 알려줘."
        ),
        proposed_response="피드는 잉크를 공급하고 닙은 종이에 닿는 부분입니다.",
        model=None,
        tool_history=[],
    )

    assert review.grounded is True
    assert review.task_aligned is False
    assert review.missing_aspects
    schema = captured["schema"]
    assert set(schema["properties"]) == {"grounded", "task_aligned", "missing_aspects"}
    assert set(schema["required"]) == {"grounded", "task_aligned", "missing_aspects"}
    prompt = str(captured["system"]).lower()
    assert "task alignment" in prompt
    assert "actual outcomes" in prompt
    assert "nearby, substituted" in prompt


@pytest.mark.asyncio
async def test_passing_final_review_requires_both_grounding_and_alignment(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({
            "grounded": True,
            "task_aligned": True,
            "missing_aspects": [],
        })

    monkeypatch.setattr(grounding_tools, "ollama_chat", fake_chat)
    review = await review_final_grounding(
        system="system",
        user_message="Current user message:\n안정적인 답을 줘",
        proposed_response="요청에 직접 답한 안정적인 답입니다.",
        model=None,
        tool_history=[],
    )

    assert review.grounded is True
    assert review.task_aligned is True
    assert review.missing_aspects == ()
