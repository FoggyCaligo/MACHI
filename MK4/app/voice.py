from __future__ import annotations

import asyncio
import importlib.util
import re
import tempfile
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

    STT uses faster-whisper ``small`` by default. TTS uses the Apache-2.0
    Qwen3-TTS 12Hz 0.6B CustomVoice model with the Korean ``Sohee`` speaker.
    Missing default models are downloaded into MK4's managed voice-model directory
    on first prepare/use and then reused locally. Loaded model objects stay cached
    in the server process across turns.
    """

    def __init__(self) -> None:
        self._stt_model: Any | None = None
        self._tts_model: Any | None = None
        self._stt_load_lock = Lock()
        self._tts_load_lock = Lock()

    def status(self) -> VoiceStatus:
        return VoiceStatus(
            stt_configured=bool(config.VOICE_STT_MODEL),
            tts_configured=bool(config.VOICE_TTS_MODEL_PATH or config.VOICE_TTS_MODEL),
            stt_library_available=importlib.util.find_spec("faster_whisper") is not None,
            tts_library_available=importlib.util.find_spec("qwen_tts") is not None,
            prepared=self._stt_model is not None and self._tts_model is not None,
        )

    async def prepare(self) -> VoiceStatus:
        status = self.status()
        if not status.stt_library_available:
            raise RuntimeError("faster-whisper is not installed; run pip install -r MK4/requirements.txt")
        if not status.tts_library_available:
            raise RuntimeError("qwen-tts is not installed; run pip install -r MK4/requirements.txt")

        await asyncio.wait_for(
            asyncio.gather(
                asyncio.to_thread(self._get_stt_model),
                asyncio.to_thread(self._get_tts_model),
            ),
            timeout=config.VOICE_PREPARE_TIMEOUT_SECONDS,
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
        if importlib.util.find_spec("qwen_tts") is None:
            raise RuntimeError("qwen-tts is not installed; run pip install -r MK4/requirements.txt")

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
                raise RuntimeError("Qwen3-TTS did not create a valid WAV file")
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
        import soundfile as sf

        model = self._get_tts_model()
        wavs, sample_rate = model.generate_custom_voice(
            text=text,
            language=config.VOICE_TTS_LANGUAGE,
            speaker=config.VOICE_TTS_SPEAKER,
            instruct=config.VOICE_TTS_INSTRUCT or None,
        )
        if not wavs:
            raise RuntimeError("Qwen3-TTS returned no audio")
        sf.write(str(output_path), wavs[0], sample_rate)

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

    def _get_tts_model(self):
        if self._tts_model is not None:
            return self._tts_model
        with self._tts_load_lock:
            if self._tts_model is None:
                import torch
                from qwen_tts import Qwen3TTSModel

                model_path = _ensure_qwen_tts_model()
                device_map, dtype = _resolve_qwen_runtime(torch)
                self._tts_model = Qwen3TTSModel.from_pretrained(
                    str(model_path),
                    device_map=device_map,
                    dtype=dtype,
                )
        return self._tts_model


def _voice_model_root() -> Path:
    root = Path(config.VOICE_MODEL_DIR).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _stt_download_root() -> Path:
    return _voice_model_root() / "faster-whisper"


def _qwen_tts_download_root() -> Path:
    model_name = re.sub(r"[^A-Za-z0-9._-]+", "-", config.VOICE_TTS_MODEL).strip("-")
    return _voice_model_root() / (model_name or "qwen3-tts")


def _ensure_qwen_tts_model() -> Path:
    if config.VOICE_TTS_MODEL_PATH:
        custom_path = Path(config.VOICE_TTS_MODEL_PATH).expanduser().resolve()
        if not custom_path.is_dir():
            raise RuntimeError(f"Custom Qwen3-TTS model directory not found: {custom_path}")
        return custom_path

    model_dir = _qwen_tts_download_root()
    if (model_dir / "config.json").is_file() and (model_dir / "model.safetensors").is_file():
        return model_dir
    if not config.VOICE_AUTO_DOWNLOAD:
        raise RuntimeError(
            "Qwen3-TTS model is not downloaded. Enable MK4_VOICE_AUTO_DOWNLOAD "
            "or provide MK4_TTS_MODEL_PATH."
        )

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface-hub is required to download Qwen3-TTS") from exc

    model_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=config.VOICE_TTS_MODEL,
        local_dir=str(model_dir),
    )
    if not (model_dir / "config.json").is_file() or not (model_dir / "model.safetensors").is_file():
        raise RuntimeError(f"Qwen3-TTS download did not produce expected model files: {model_dir}")
    return model_dir


def _resolve_qwen_runtime(torch_module) -> tuple[str, Any]:
    requested_device = str(config.VOICE_TTS_DEVICE or "auto").strip().lower()
    if requested_device == "auto":
        device_map = "cuda:0" if torch_module.cuda.is_available() else "cpu"
    else:
        device_map = requested_device

    requested_dtype = str(config.VOICE_TTS_DTYPE or "auto").strip().lower()
    dtype_map = {
        "float32": torch_module.float32,
        "fp32": torch_module.float32,
        "float16": torch_module.float16,
        "fp16": torch_module.float16,
        "bfloat16": torch_module.bfloat16,
        "bf16": torch_module.bfloat16,
    }
    if requested_dtype != "auto":
        if requested_dtype not in dtype_map:
            raise RuntimeError(f"Unsupported MK4_TTS_DTYPE: {config.VOICE_TTS_DTYPE}")
        return device_map, dtype_map[requested_dtype]

    if device_map.startswith("cuda"):
        supports_bf16 = getattr(torch_module.cuda, "is_bf16_supported", lambda: False)()
        return device_map, torch_module.bfloat16 if supports_bf16 else torch_module.float16
    return device_map, torch_module.float32
