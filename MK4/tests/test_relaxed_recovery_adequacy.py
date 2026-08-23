from __future__ import annotations

import json
from pathlib import Path

import pytest

from MK4.tools import relaxed_adequacy
from MK4.tools.tool_requirements import FrozenToolRequirements, ToolEvaluation


def _requirements() -> FrozenToolRequirements:
    return FrozenToolRequirements(
        evaluations=(ToolEvaluation(tool="web_research", required=True),),
    )


def _event() -> dict:
    return {
        "tool": "web_research",
        "arguments": {"objective": "specific models", "language": "en"},
        "result": {"ok": True, "results": [{"title": "relevant current result"}]},
    }


@pytest.mark.asyncio
async def test_relaxed_adequacy_is_release_gate_not_quality_checklist(monkeypatch) -> None:
    captured = {}

    async def fake_chat(*, system, user, model, response_format):
        captured["system"] = system
        captured["payload"] = json.loads(user)
        return json.dumps({"adequate": True, "missing_aspects": []})

    monkeypatch.setattr(relaxed_adequacy, "ollama_chat", fake_chat)

    result = await relaxed_adequacy.review_relaxed_tool_result_adequacy(
        system="system",
        user_message="recommend a few good models",
        model=None,
        requirements=_requirements(),
        tool_history=[_event()],
    )

    assert result.adequate is True
    prompt = captured["system"].lower()
    assert "release gate, not a quality-improvement checklist" in prompt
    assert "material error" in prompt
    assert "could reasonably differ today from yesterday" in prompt
    assert "sufficient to answer what the user actually asked for" in prompt
    assert "more detail, more sources, deeper comparison" in prompt
    assert captured["payload"]["user_request"] == "recommend a few good models"


@pytest.mark.asyncio
async def test_relaxed_adequacy_requires_empty_missing_aspects_when_adequate(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({"adequate": True, "missing_aspects": ["optional improvement"]})

    monkeypatch.setattr(relaxed_adequacy, "ollama_chat", fake_chat)

    with pytest.raises(RuntimeError, match="must not include missing aspects"):
        await relaxed_adequacy.review_relaxed_tool_result_adequacy(
            system="system",
            user_message="request",
            model=None,
            requirements=_requirements(),
            tool_history=[_event()],
        )


def test_gitignore_tracks_database_files_but_ignores_sqlite_sidecars() -> None:
    root = Path(__file__).resolve().parents[2]
    lines = {
        line.strip()
        for line in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "MK4/data/*.db" not in lines
    assert "MK5/data/*.db" not in lines
    assert "MK4/data/*.db-*" in lines
    assert "MK5/data/*.db-*" in lines
