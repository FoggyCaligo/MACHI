from __future__ import annotations

import sys
import wave
from pathlib import Path
from types import ModuleType, SimpleNamespace

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


class _FakeSynthesisConfig:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _FakePiperVoice:
    def __init__(self) -> None:
        self.calls = 0

    def synthesize_wav(self, text: str, wav_file, *, syn_config=None) -> None:
        self.calls += 1
        assert text == "안녕하세요"
        assert isinstance(syn_config, _FakeSynthesisConfig)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 100)


@pytest.mark.asyncio
async def test_stt_uses_reusable_faster_whisper_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_STT_MODEL", "small")
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


def test_faster_whisper_uses_managed_download_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    fake_module = ModuleType("faster_whisper")

    class FakeModel:
        def __init__(self, model_name, **kwargs):
            seen["model_name"] = model_name
            seen.update(kwargs)

    fake_module.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(config, "VOICE_STT_MODEL", "small")
    monkeypatch.setattr(config, "VOICE_STT_DEVICE", "cpu")
    monkeypatch.setattr(config, "VOICE_STT_COMPUTE_TYPE", "int8")
    monkeypatch.setattr(config, "VOICE_STT_CPU_THREADS", 4)
    monkeypatch.setattr(config, "VOICE_AUTO_DOWNLOAD", True)
    monkeypatch.setattr(config, "VOICE_MODEL_DIR", tmp_path)

    service = LocalVoiceService()
    first = service._get_stt_model()
    second = service._get_stt_model()

    assert first is second
    assert seen["model_name"] == "small"
    assert Path(str(seen["download_root"])) == tmp_path / "faster-whisper"
    assert seen["local_files_only"] is False


@pytest.mark.asyncio
async def test_tts_uses_current_piper_synthesize_wav_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_path = tmp_path / "custom.onnx"
    config_path = tmp_path / "custom.onnx.json"
    model_path.write_bytes(b"model")
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "VOICE_TTS_MODEL_PATH", str(model_path))
    monkeypatch.setattr(config, "VOICE_TTS_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config, "VOICE_TTS_SPEAKER_ID", None)
    monkeypatch.setattr(config, "VOICE_TTS_LENGTH_SCALE", None)
    monkeypatch.setattr(config, "VOICE_MAX_TTS_CHARS", 6000)
    monkeypatch.setattr(config, "VOICE_INFERENCE_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: object())

    fake_piper = ModuleType("piper")
    fake_piper.SynthesisConfig = _FakeSynthesisConfig
    monkeypatch.setitem(sys.modules, "piper", fake_piper)

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


def test_default_piper_voice_auto_downloads_into_managed_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_MODEL_DIR", tmp_path)
    monkeypatch.setattr(config, "VOICE_TTS_MODEL_PATH", "")
    monkeypatch.setattr(config, "VOICE_TTS_CONFIG_PATH", "")
    monkeypatch.setattr(config, "VOICE_TTS_VOICE", "ko_KR-kss-medium")
    monkeypatch.setattr(config, "VOICE_AUTO_DOWNLOAD", True)

    piper_package = ModuleType("piper")
    piper_package.__path__ = []
    download_module = ModuleType("piper.download_voices")

    def fake_download(voice_name: str, download_dir: Path) -> None:
        assert voice_name == "ko_KR-kss-medium"
        download_dir.mkdir(parents=True, exist_ok=True)
        (download_dir / f"{voice_name}.onnx").write_bytes(b"model")
        (download_dir / f"{voice_name}.onnx.json").write_text("{}", encoding="utf-8")

    download_module.download_voice = fake_download
    monkeypatch.setitem(sys.modules, "piper", piper_package)
    monkeypatch.setitem(sys.modules, "piper.download_voices", download_module)

    model_path, config_path = voice._ensure_tts_model()

    assert model_path == tmp_path / "piper" / "ko_KR-kss-medium.onnx"
    assert config_path == tmp_path / "piper" / "ko_KR-kss-medium.onnx.json"
    assert model_path.is_file()
    assert config_path.is_file()


def test_custom_piper_voice_overrides_default_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_path = tmp_path / "my-voice.onnx"
    config_path = tmp_path / "my-voice.onnx.json"
    model_path.write_bytes(b"custom")
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "VOICE_TTS_MODEL_PATH", str(model_path))
    monkeypatch.setattr(config, "VOICE_TTS_CONFIG_PATH", "")
    monkeypatch.setattr(config, "VOICE_TTS_VOICE", "ko_KR-kss-medium")

    resolved_model, resolved_config = voice._ensure_tts_model()

    assert resolved_model == model_path.resolve()
    assert resolved_config == config_path.resolve()


def test_voice_status_is_zero_config_when_libraries_are_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    service = LocalVoiceService()
    monkeypatch.setattr(config, "VOICE_STT_MODEL", "small")
    monkeypatch.setattr(config, "VOICE_TTS_MODEL_PATH", "")
    monkeypatch.setattr(config, "VOICE_TTS_VOICE", "ko_KR-kss-medium")
    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: object())

    status = service.status()
    assert status.ready is True
    assert status.prepared is False

    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: None if name == "piper" else object())
    assert service.status().ready is False


def test_voice_static_assets_describe_continuous_loop_and_first_run_prepare() -> None:
    static_dir = Path(__file__).resolve().parents[1] / "app" / "static"
    js = (static_dir / "voice-mode.js").read_text(encoding="utf-8")
    css = (static_dir / "voice-mode.css").read_text(encoding="utf-8")

    assert 'insertBefore($voiceBtn, $attachBtn)' in js
    assert 'fetch("/voice/prepare"' in js
    assert 'fetch("/voice/stt"' in js
    assert 'fetch("/voice/tts"' in js
    assert '$sendBtn.click()' in js
    assert "SILENCE_TO_SEND_MS = 900" in js
    assert "state.speaking" in js
    assert "encodeWav" in js
    assert "첫 실행 시 모델을 자동 설치합니다" in js
    assert "#voice-mode-btn.active" in css


def test_ui_injects_voice_assets() -> None:
    from MK4.app.server import _render_ui_html

    html = _render_ui_html()
    assert '/static/voice-mode.css' in html
    assert '/static/voice-mode.js' in html


def test_requirements_include_python_voice_libraries() -> None:
    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    assert "faster-whisper" in requirements
    assert "piper-tts>=1.6.0" in requirements


def test_default_voice_configuration_is_documented() -> None:
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "MK4_VOICE_AUTO_DOWNLOAD=true" in example
    assert "MK4_STT_MODEL=small" in example
    assert "MK4_TTS_VOICE=ko_KR-kss-medium" in example
    assert "MK4_TTS_MODEL_PATH=" in example
