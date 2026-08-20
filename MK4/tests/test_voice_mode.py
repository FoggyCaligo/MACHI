from __future__ import annotations

from pathlib import Path

import pytest

from MK4 import config
from MK4.app import voice
from MK4.app.voice import LocalVoiceService


@pytest.mark.asyncio
async def test_stt_uses_local_command_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_STT_COMMAND", "local-stt --input {input}")
    monkeypatch.setattr(config, "VOICE_MAX_AUDIO_BYTES", 1024 * 1024)
    seen: dict[str, object] = {}

    async def fake_run(command: str, *, stdin: bytes | None = None):
        seen["command"] = command
        seen["stdin"] = stdin
        return "안녕하세요 MK4".encode("utf-8"), b"", 0

    monkeypatch.setattr(voice, "_run_command", fake_run)
    text = await LocalVoiceService().transcribe(b"RIFF" + b"\x00" * 100)

    assert text == "안녕하세요 MK4"
    assert "local-stt --input" in str(seen["command"])
    assert "speech.wav" in str(seen["command"])
    assert seen["stdin"] is None


@pytest.mark.asyncio
async def test_stt_can_read_exact_output_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_STT_COMMAND", "local-stt {input} --output {output}")
    monkeypatch.setattr(config, "VOICE_MAX_AUDIO_BYTES", 1024 * 1024)

    async def fake_run(command: str, *, stdin: bytes | None = None):
        marker = "--output "
        output_text = command.split(marker, 1)[1].strip().strip('"')
        Path(output_text).write_text("출력 파일 인식", encoding="utf-8")
        return b"", b"", 0

    monkeypatch.setattr(voice, "_run_command", fake_run)
    text = await LocalVoiceService().transcribe(b"RIFF" + b"\x00" * 100)

    assert text == "출력 파일 인식"


def test_voice_status_requires_both_local_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    service = LocalVoiceService()
    monkeypatch.setattr(config, "VOICE_STT_COMMAND", "stt {input}")
    monkeypatch.setattr(config, "VOICE_TTS_COMMAND", "")
    assert service.status().ready is False

    monkeypatch.setattr(config, "VOICE_TTS_COMMAND", "tts --output {output}")
    assert service.status().ready is True


def test_voice_static_assets_describe_continuous_loop() -> None:
    static_dir = Path(__file__).resolve().parents[1] / "app" / "static"
    js = (static_dir / "voice-mode.js").read_text(encoding="utf-8")
    css = (static_dir / "voice-mode.css").read_text(encoding="utf-8")

    assert 'insertBefore($voiceBtn, $attachBtn)' in js
    assert 'fetch("/voice/stt"' in js
    assert 'fetch("/voice/tts"' in js
    assert '$sendBtn.click()' in js
    assert "SILENCE_TO_SEND_MS = 900" in js
    assert "state.speaking" in js
    assert "encodeWav" in js
    assert "#voice-mode-btn.active" in css


def test_ui_injects_voice_assets() -> None:
    from MK4.app.server import _render_ui_html

    html = _render_ui_html()
    assert '/static/voice-mode.css' in html
    assert '/static/voice-mode.js' in html
