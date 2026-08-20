from __future__ import annotations

import json

import pytest

from MK4 import config
from MK4.app import server


def test_voice_assets_are_not_injected_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_ENABLED", False)

    html = server._render_ui_html()

    assert "/static/markdown-render.css" in html
    assert "/static/markdown-render.js" in html
    assert "/static/voice-mode.css" not in html
    assert "/static/voice-mode.js" not in html


def test_voice_assets_are_injected_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_ENABLED", True)

    html = server._render_ui_html()

    assert "/static/voice-mode.css" in html
    assert "/static/voice-mode.js" in html


@pytest.mark.asyncio
async def test_voice_status_reports_disabled_without_touching_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_ENABLED", False)

    def fail_status():
        raise AssertionError("voice_service.status must not run while voice is disabled")

    monkeypatch.setattr(server.voice_service, "status", fail_status)
    result = await server.voice_status()

    assert result == {
        "ok": True,
        "enabled": False,
        "ready": False,
        "prepared": False,
        "auto_download": False,
        "mode": "disabled",
    }


@pytest.mark.asyncio
async def test_voice_prepare_is_blocked_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_ENABLED", False)

    async def fail_prepare():
        raise AssertionError("voice_service.prepare must not run while voice is disabled")

    monkeypatch.setattr(server.voice_service, "prepare", fail_prepare)
    response = await server.voice_prepare()
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 403
    assert payload["error"] == "voice_disabled"


def test_env_example_documents_voice_enabled_toggle() -> None:
    example = (server.Path(server._STATIC_DIR).parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "MK4_VOICE_ENABLED=true" in example
