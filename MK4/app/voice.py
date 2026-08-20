from __future__ import annotations

import asyncio
import importlib.util
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from .. import config


@dataclass(frozen=True, slots=True)
class VoiceStatus:
    stt_configured: bool
    tts_configured: bool
    stt_library_available: bool
    tts_library_available: bool
    prepared: bool

    @property
    def ready(self) -> bool:
        return (
            self.stt_configured
            and self.tts_configured
            and self.stt_library_available
            and self.tts_library_available
        )


class LocalVoiceService:
    """Reusable Python-native STT/TTS service with first-run model provisioning.

    Defaults use faster-whisper ``small`` and Piper ``ko_KR-kss-medium``. When
    auto-download is enabled, the first prepare/use downloads missing models into
    MK4's voice model directory. Loaded model objects are retained for later turns.

    A custom Piper .onnx path always wins over the default voice and is never
    replaced or downloaded over by this service.
    """

    def __init__(self) -> None:
        self._stt_model: Any | None = None
        self._tts_voice: Any | None = None
        self._stt_load_lock = Lock()
        self._tts_load_lock = Lock()

    def status(self) -> VoiceStatus:
        return VoiceStatus(
            stt_configured=bool(config.VOICE_STT_MODEL),
            tts_configured=bool(config.VOICE_TTS_MODEL_PATH or config.VOICE_TTS_VOICE),
            stt_library_available=importlib.util.find_spec("faster_whisper") is not None,
            tts_library_available=importlib.util.find_spec("piper") is not None,
            prepared=self._stt_model is not None and self._tts_voice is not None,
        )

    async def prepare(self) -> VoiceStatus:
        status = self.status()
        if not status.stt_library_available:
            raise RuntimeError("faster-whisper is not installed; run pip install -r MK4/requirements.txt")
        if not status.tts_library_available:
            raise RuntimeError("piper-tts is not installed; run pip install -r MK4/requirements.txt")

        await asyncio.wait_for(
            asyncio.gather(
                asyncio.to_thread(self._get_stt_model),
                asyncio.to_thread(self._get_tts_voice),
            ),
            timeout=config.VOICE_INFERENCE_TIMEOUT_SECONDS,
        )
        return self.status()

    async def transcribe(self, audio_bytes: bytes) -> str:
        if not config.VOICE_STT_MODEL:
            raise RuntimeError("MK4_STT_MODEL is not configured")
        if len(audio_bytes) > config.VOICE_MAX_AUDIO_BYTES:
            raise ValueError(
                f"Voice input is too large ({len(audio_bytes)} bytes; max={config.VOICE_MAX_AUDIO_BYTES})"
            )
        if importlib.util.find_spec("faster_whisper") is None:
            raise RuntimeError("faster-whisper is not installed; run pip install -r MK4/requirements.txt")

        with tempfile.TemporaryDirectory(prefix="mk4-stt-") as temp_dir:
            input_path = Path(temp_dir) / "speech.wav"
            input_path.write_bytes(audio_bytes)
            text = await asyncio.wait_for(
                asyncio.to_thread(self._transcribe_sync, input_path),
                timeout=config.VOICE_INFERENCE_TIMEOUT_SECONDS,
            )
        if not text:
            raise RuntimeError("faster-whisper returned an empty transcription")
        return text

    async def synthesize(self, text: str) -> Path:
        if importlib.util.find_spec("piper") is None:
            raise RuntimeError("piper-tts is not installed; run pip install -r MK4/requirements.txt")

        clean_text = str(text or "").strip()
        if not clean_text:
            raise ValueError("TTS text is empty")
        if len(clean_text) > config.VOICE_MAX_TTS_CHARS:
            clean_text = clean_text[: config.VOICE_MAX_TTS_CHARS]

        handle = tempfile.NamedTemporaryFile(prefix="mk4-tts-", suffix=".wav", delete=False)
        handle.close()
        output_path = Path(handle.name)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._synthesize_sync, clean_text, output_path),
                timeout=config.VOICE_INFERENCE_TIMEOUT_SECONDS,
            )
            if not output_path.exists() or output_path.stat().st_size <= 44:
                raise RuntimeError("Piper did not create a valid WAV file")
            return output_path
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

    def _transcribe_sync(self, input_path: Path) -> str:
        model = self._get_stt_model()
        language = config.VOICE_STT_LANGUAGE or None
        segments, _info = model.transcribe(
            str(input_path),
            language=language,
            beam_size=config.VOICE_STT_BEAM_SIZE,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()

    def _synthesize_sync(self, text: str, output_path: Path) -> None:
        from piper import SynthesisConfig

        voice = self._get_tts_voice()
        syn_config = SynthesisConfig(
            speaker_id=config.VOICE_TTS_SPEAKER_ID,
            length_scale=config.VOICE_TTS_LENGTH_SCALE,
        )
        with wave.open(str(output_path), "wb") as wav_file:
            voice.synthesize_wav(text, wav_file, syn_config=syn_config)

    def _get_stt_model(self):
        if self._stt_model is not None:
            return self._stt_model
        with self._stt_load_lock:
            if self._stt_model is None:
                from faster_whisper import WhisperModel

                download_root = _stt_download_root()
                download_root.mkdir(parents=True, exist_ok=True)
                self._stt_model = WhisperModel(
                    config.VOICE_STT_MODEL,
                    device=config.VOICE_STT_DEVICE,
                    compute_type=config.VOICE_STT_COMPUTE_TYPE,
                    cpu_threads=config.VOICE_STT_CPU_THREADS,
                    download_root=str(download_root),
                    local_files_only=not config.VOICE_AUTO_DOWNLOAD,
                )
        return self._stt_model

    def _get_tts_voice(self):
        if self._tts_voice is not None:
            return self._tts_voice
        with self._tts_load_lock:
            if self._tts_voice is None:
                from piper import PiperVoice

                model_path, config_path = _ensure_tts_model()
                self._tts_voice = PiperVoice.load(
                    model_path,
                    config_path=config_path,
                    use_cuda=False,
                    download_dir=_piper_download_root(),
                )
        return self._tts_voice


def _voice_model_root() -> Path:
    root = Path(config.VOICE_MODEL_DIR).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _stt_download_root() -> Path:
    return _voice_model_root() / "faster-whisper"


def _piper_download_root() -> Path:
    root = _voice_model_root() / "piper"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ensure_tts_model() -> tuple[Path, Path | None]:
    if config.VOICE_TTS_MODEL_PATH:
        model_path = Path(config.VOICE_TTS_MODEL_PATH).expanduser().resolve()
        if not model_path.is_file():
            raise RuntimeError(f"Custom Piper voice model not found: {model_path}")
        if config.VOICE_TTS_CONFIG_PATH:
            config_path = Path(config.VOICE_TTS_CONFIG_PATH).expanduser().resolve()
            if not config_path.is_file():
                raise RuntimeError(f"Custom Piper voice config not found: {config_path}")
        else:
            config_path = Path(f"{model_path}.json")
            if not config_path.is_file():
                raise RuntimeError(f"Piper voice config not found: {config_path}")
        return model_path, config_path

    voice_name = str(config.VOICE_TTS_VOICE or "").strip()
    if not voice_name:
        raise RuntimeError("MK4_TTS_VOICE is not configured")

    download_root = _piper_download_root()
    model_path = download_root / f"{voice_name}.onnx"
    config_path = download_root / f"{voice_name}.onnx.json"
    if not model_path.is_file() or not config_path.is_file():
        if not config.VOICE_AUTO_DOWNLOAD:
            raise RuntimeError(
                f"Piper voice is not downloaded: {voice_name}. Enable MK4_VOICE_AUTO_DOWNLOAD or provide MK4_TTS_MODEL_PATH."
            )
        from piper.download_voices import download_voice

        download_voice(voice_name, download_root)

    if not model_path.is_file() or not config_path.is_file():
        raise RuntimeError(f"Piper voice download did not produce expected files for {voice_name}")
    return model_path, config_path
