from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from MK4 import config
from MK4.app import voice
from MK4.app.voice import LocalVoiceService


class _FakeWhisperModel:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, path: str, **kwargs):
        self.calls += 1
        assert Path(path).name == "speech.wav"
        assert kwargs["language"] == "ko"
        assert kwargs["vad_filter"] is True
        assert kwargs["condition_on_previous_text"] is False
        return iter([
            SimpleNamespace(text=" 안녕하세요 "),
            SimpleNamespace(text=" MK4 "),
        ]), SimpleNamespace(language="ko")


class _FakePiperVoice:
    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, text: str, wav_file, **kwargs) -> None:
        self.calls += 1
        assert text == "안녕하세요"
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 100)


@pytest.mark.asyncio
async def test_stt_uses_reusable_faster_whisper_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_STT_MODEL", "local-whisper-model")
    monkeypatch.setattr(config, "VOICE_STT_LANGUAGE", "ko")
    monkeypatch.setattr(config, "VOICE_STT_BEAM_SIZE", 1)
    monkeypatch.setattr(config, "VOICE_MAX_AUDIO_BYTES", 1024 * 1024)
    monkeypatch.setattr(config, "VOICE_INFERENCE_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: object())

    service = LocalVoiceService()
    model = _FakeWhisperModel()
    monkeypatch.setattr(service, "_get_stt_model", lambda: model)

    first = await service.transcribe(b"RIFF" + b"\x00" * 100)
    second = await service.transcribe(b"RIFF" + b"\x00" * 100)

    assert first == "안녕하세요 MK4"
    assert second == "안녕하세요 MK4"
    assert model.calls == 2


@pytest.mark.asyncio
async def test_tts_uses_piper_voice_and_writes_wav(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_path = tmp_path / "ko_voice.onnx"
    model_path.write_bytes(b"model")
    monkeypatch.setattr(config, "VOICE_TTS_MODEL_PATH", str(model_path))
    monkeypatch.setattr(config, "VOICE_TTS_CONFIG_PATH", "")
    monkeypatch.setattr(config, "VOICE_TTS_SPEAKER_ID", None)
    monkeypatch.setattr(config, "VOICE_TTS_LENGTH_SCALE", None)
    monkeypatch.setattr(config, "VOICE_TTS_SENTENCE_SILENCE", None)
    monkeypatch.setattr(config, "VOICE_MAX_TTS_CHARS", 6000)
    monkeypatch.setattr(config, "VOICE_INFERENCE_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: object())

    service = LocalVoiceService()
    fake_voice = _FakePiperVoice()
    monkeypatch.setattr(service, "_get_tts_voice", lambda: fake_voice)

    output_path = await service.synthesize("안녕하세요")
    try:
        assert output_path.exists()
        with wave.open(str(output_path), "rb") as wav_file:
            assert wav_file.getframerate() == 16000
            assert wav_file.getnchannels() == 1
        assert fake_voice.calls == 1
    finally:
        output_path.unlink(missing_ok=True)


def test_voice_status_requires_models_and_python_libraries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = LocalVoiceService()
    model_path = tmp_path / "voice.onnx"
    model_path.write_bytes(b"model")

    monkeypatch.setattr(config, "VOICE_STT_MODEL", "local-whisper")
    monkeypatch.setattr(config, "VOICE_TTS_MODEL_PATH", str(model_path))
    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: object())
    status = service.status()
    assert status.ready is True
    assert status.stt_library_available is True
    assert status.tts_library_available is True

    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: None if name == "piper" else object())
    assert service.status().ready is False


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


def test_requirements_include_python_voice_libraries() -> None:
    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    assert "faster-whisper" in requirements
    assert "piper-tts" in requirements
