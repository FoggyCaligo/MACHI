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
        captured["schema"] = response_format
        return json.dumps({"adequate": True, "blocking_defects": []})

    monkeypatch.setattr(relaxed_adequacy, "ollama_chat", fake_chat)

    result = await relaxed_adequacy.review_relaxed_tool_result_adequacy(
        system="system",
        user_message="recommend a few good models",
        model=None,
        requirements=_requirements(),
        tool_history=[_event()],
    )

    assert result.adequate is True
    assert result.missing_aspects == ()
    prompt = captured["system"].lower()
    assert "release gate, not a quality-improvement checklist" in prompt
    assert "material error" in prompt
    assert "could reasonably differ today from yesterday" in prompt
    assert "sufficient to answer what the user actually asked for" in prompt
    assert "more detail, more sources, deeper comparison" in prompt
    assert "personalization" in prompt
    assert "requested_aspect" in prompt
    assert "evidence_defect" in prompt
    assert captured["payload"]["user_request"] == "recommend a few good models"
    defect_schema = captured["schema"]["properties"]["blocking_defects"]["items"]
    assert set(defect_schema["required"]) == {"requested_aspect", "evidence_defect"}


@pytest.mark.asyncio
async def test_relaxed_adequacy_requires_empty_blocking_defects_when_adequate(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({
            "adequate": True,
            "blocking_defects": [{
                "requested_aspect": "recommend one beginner pen",
                "evidence_defect": "optional preference information is missing",
            }],
        })

    monkeypatch.setattr(relaxed_adequacy, "ollama_chat", fake_chat)

    with pytest.raises(RuntimeError, match="must not include blocking defects"):
        await relaxed_adequacy.review_relaxed_tool_result_adequacy(
            system="system",
            user_message="request",
            model=None,
            requirements=_requirements(),
            tool_history=[_event()],
        )


@pytest.mark.asyncio
async def test_inadequacy_requires_requested_aspect_and_concrete_evidence_defect(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({
            "adequate": False,
            "blocking_defects": [{
                "requested_aspect": "compare three pens under 50,000 KRW",
                "evidence_defect": "the successful results contain no current price evidence",
            }],
        })

    monkeypatch.setattr(relaxed_adequacy, "ollama_chat", fake_chat)

    result = await relaxed_adequacy.review_relaxed_tool_result_adequacy(
        system="system",
        user_message="compare three beginner fountain pens under 50,000 KRW",
        model=None,
        requirements=_requirements(),
        tool_history=[_event()],
    )

    assert result.adequate is False
    assert result.missing_aspects == (
        "Requested aspect: compare three pens under 50,000 KRW; "
        "evidence defect: the successful results contain no current price evidence",
    )


@pytest.mark.asyncio
async def test_inadequacy_without_blocking_defect_fails_visibly(monkeypatch) -> None:
    async def fake_chat(*, system, user, model, response_format):
        return json.dumps({"adequate": False, "blocking_defects": []})

    monkeypatch.setattr(relaxed_adequacy, "ollama_chat", fake_chat)

    with pytest.raises(RuntimeError, match="must identify at least one blocking defect"):
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
