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


class _FakeQwenTTSModel:
    def __init__(self) -> None:
        self.calls = 0
        self.last_kwargs: dict[str, object] = {}

    def generate_custom_voice(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return [[0.0] * 240], 24000


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
async def test_tts_uses_qwen_sohee_custom_voice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_TTS_SPEAKER", "Sohee")
    monkeypatch.setattr(config, "VOICE_TTS_LANGUAGE", "Korean")
    monkeypatch.setattr(config, "VOICE_TTS_INSTRUCT", "차분하고 안정적인 말투로 자연스럽게 말해줘.")
    monkeypatch.setattr(config, "VOICE_MAX_TTS_CHARS", 6000)
    monkeypatch.setattr(config, "VOICE_INFERENCE_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: object())

    fake_soundfile = ModuleType("soundfile")

    def fake_write(path: str, samples, sample_rate: int) -> None:
        assert sample_rate == 24000
        assert len(samples) == 240
        with wave.open(path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * len(samples))

    fake_soundfile.write = fake_write
    monkeypatch.setitem(sys.modules, "soundfile", fake_soundfile)

    service = LocalVoiceService()
    fake_model = _FakeQwenTTSModel()
    monkeypatch.setattr(service, "_get_tts_model", lambda: fake_model)

    output_path = await service.synthesize("안녕하세요")
    try:
        assert output_path.exists()
        with wave.open(str(output_path), "rb") as wav_file:
            assert wav_file.getframerate() == 24000
            assert wav_file.getnchannels() == 1
        assert fake_model.calls == 1
        assert fake_model.last_kwargs["text"] == "안녕하세요"
        assert fake_model.last_kwargs["speaker"] == "Sohee"
        assert fake_model.last_kwargs["language"] == "Korean"
        assert "차분" in str(fake_model.last_kwargs["instruct"])
    finally:
        output_path.unlink(missing_ok=True)


def test_default_qwen_tts_auto_downloads_into_managed_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "VOICE_MODEL_DIR", tmp_path)
    monkeypatch.setattr(config, "VOICE_TTS_MODEL_PATH", "")
    monkeypatch.setattr(config, "VOICE_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    monkeypatch.setattr(config, "VOICE_AUTO_DOWNLOAD", True)
    seen: dict[str, object] = {}

    hub_module = ModuleType("huggingface_hub")

    def fake_snapshot_download(*, repo_id: str, local_dir: str) -> str:
        seen["repo_id"] = repo_id
        seen["local_dir"] = local_dir
        target = Path(local_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "config.json").write_text("{}", encoding="utf-8")
        (target / "model.safetensors").write_bytes(b"model")
        return str(target)

    hub_module.snapshot_download = fake_snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub_module)

    model_path = voice._ensure_qwen_tts_model()

    assert seen["repo_id"] == "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert model_path == tmp_path / "Qwen-Qwen3-TTS-12Hz-0.6B-CustomVoice"
    assert (model_path / "config.json").is_file()
    assert (model_path / "model.safetensors").is_file()


def test_local_qwen_tts_model_directory_overrides_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_path = tmp_path / "custom-qwen-tts"
    custom_path.mkdir()
    (custom_path / "config.json").write_text("{}", encoding="utf-8")
    (custom_path / "model.safetensors").write_bytes(b"model")
    monkeypatch.setattr(config, "VOICE_TTS_MODEL_PATH", str(custom_path))

    assert voice._ensure_qwen_tts_model() == custom_path.resolve()


def test_qwen_runtime_auto_falls_back_to_cpu_float32(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_torch = SimpleNamespace(
        float32=object(),
        float16=object(),
        bfloat16=object(),
        cuda=SimpleNamespace(is_available=lambda: False, is_bf16_supported=lambda: False),
    )
    monkeypatch.setattr(config, "VOICE_TTS_DEVICE", "auto")
    monkeypatch.setattr(config, "VOICE_TTS_DTYPE", "auto")

    device, dtype = voice._resolve_qwen_runtime(fake_torch)

    assert device == "cpu"
    assert dtype is fake_torch.float32


def test_voice_status_is_zero_config_when_libraries_are_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    service = LocalVoiceService()
    monkeypatch.setattr(config, "VOICE_STT_MODEL", "small")
    monkeypatch.setattr(config, "VOICE_TTS_MODEL_PATH", "")
    monkeypatch.setattr(config, "VOICE_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: object())

    status = service.status()
    assert status.ready is True
    assert status.prepared is False

    monkeypatch.setattr(voice.importlib.util, "find_spec", lambda name: None if name == "qwen_tts" else object())
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
    assert "qwen-tts>=0.1.1" in requirements
    assert "piper-tts" not in requirements


def test_default_voice_configuration_is_documented() -> None:
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "MK4_VOICE_AUTO_DOWNLOAD=true" in example
    assert "MK4_STT_MODEL=small" in example
    assert "MK4_TTS_MODEL=Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice" in example
    assert "MK4_TTS_SPEAKER=Sohee" in example
    assert "MK4_TTS_LANGUAGE=Korean" in example
    assert "MK4_TTS_MODEL_PATH=" in example
    assert "Piper" not in example
