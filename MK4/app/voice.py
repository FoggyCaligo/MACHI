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

    @property
    def ready(self) -> bool:
        return (
            self.stt_configured
            and self.tts_configured
            and self.stt_library_available
            and self.tts_library_available
        )


class LocalVoiceService:
    """Local, reusable Python-native STT/TTS service for continuous voice mode.

    STT uses faster-whisper and TTS uses piper-tts directly inside the MK4 server
    process. Models are loaded lazily on first use and then reused for subsequent
    turns. No cloud STT/TTS API is called by this service.
    """

    def __init__(self) -> None:
        self._stt_model: Any | None = None
        self._tts_voice: Any | None = None
        self._stt_load_lock = Lock()
        self._tts_load_lock = Lock()

    def status(self) -> VoiceStatus:
        return VoiceStatus(
            stt_configured=bool(config.VOICE_STT_MODEL),
            tts_configured=_tts_model_path().is_file() if config.VOICE_TTS_MODEL_PATH else False,
            stt_library_available=importlib.util.find_spec("faster_whisper") is not None,
            tts_library_available=importlib.util.find_spec("piper") is not None,
        )

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
        model_path = _tts_model_path()
        if not config.VOICE_TTS_MODEL_PATH:
            raise RuntimeError("MK4_TTS_MODEL_PATH is not configured")
        if not model_path.is_file():
            raise RuntimeError(f"Piper voice model not found: {model_path}")
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
        voice = self._get_tts_voice()
        kwargs: dict[str, Any] = {}
        if config.VOICE_TTS_SPEAKER_ID is not None:
            kwargs["speaker_id"] = config.VOICE_TTS_SPEAKER_ID
        if config.VOICE_TTS_LENGTH_SCALE is not None:
            kwargs["length_scale"] = config.VOICE_TTS_LENGTH_SCALE
        if config.VOICE_TTS_SENTENCE_SILENCE is not None:
            kwargs["sentence_silence"] = config.VOICE_TTS_SENTENCE_SILENCE

        with wave.open(str(output_path), "wb") as wav_file:
            voice.synthesize(text, wav_file, **kwargs)

    def _get_stt_model(self):
        if self._stt_model is not None:
            return self._stt_model
        with self._stt_load_lock:
            if self._stt_model is None:
                from faster_whisper import WhisperModel

                self._stt_model = WhisperModel(
                    config.VOICE_STT_MODEL,
                    device=config.VOICE_STT_DEVICE,
                    compute_type=config.VOICE_STT_COMPUTE_TYPE,
                    cpu_threads=config.VOICE_STT_CPU_THREADS,
                )
        return self._stt_model

    def _get_tts_voice(self):
        if self._tts_voice is not None:
            return self._tts_voice
        with self._tts_load_lock:
            if self._tts_voice is None:
                from piper.voice import PiperVoice

                config_path = str(_tts_config_path()) if config.VOICE_TTS_CONFIG_PATH else None
                self._tts_voice = PiperVoice.load(
                    str(_tts_model_path()),
                    config_path=config_path,
                    use_cuda=False,
                )
        return self._tts_voice


def _tts_model_path() -> Path:
    return Path(config.VOICE_TTS_MODEL_PATH).expanduser().resolve() if config.VOICE_TTS_MODEL_PATH else Path()


def _tts_config_path() -> Path:
    return Path(config.VOICE_TTS_CONFIG_PATH).expanduser().resolve()
