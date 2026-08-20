from __future__ import annotations

import asyncio
import locale
import os
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .. import config


@dataclass(frozen=True, slots=True)
class VoiceStatus:
    stt_configured: bool
    tts_configured: bool

    @property
    def ready(self) -> bool:
        return self.stt_configured and self.tts_configured


class LocalVoiceService:
    """Bridge browser audio to user-configured local STT/TTS commands.

    No network service is used by this class. The configured commands are launched
    on the same machine as MK4. STT receives a WAV path through {input}; TTS receives
    UTF-8 text on stdin and must write a WAV file to {output}.
    """

    def status(self) -> VoiceStatus:
        return VoiceStatus(
            stt_configured=bool(config.VOICE_STT_COMMAND),
            tts_configured=bool(config.VOICE_TTS_COMMAND),
        )

    async def transcribe(self, audio_bytes: bytes) -> str:
        command_template = config.VOICE_STT_COMMAND
        if not command_template:
            raise RuntimeError("MK4_STT_COMMAND is not configured")
        if "{input}" not in command_template:
            raise RuntimeError("MK4_STT_COMMAND must contain {input}")
        if len(audio_bytes) > config.VOICE_MAX_AUDIO_BYTES:
            raise ValueError(
                f"Voice input is too large ({len(audio_bytes)} bytes; max={config.VOICE_MAX_AUDIO_BYTES})"
            )

        with tempfile.TemporaryDirectory(prefix="mk4-stt-") as temp_dir:
            temp_root = Path(temp_dir)
            input_path = temp_root / "speech.wav"
            output_path = temp_root / "transcript.txt"
            input_path.write_bytes(audio_bytes)
            command = _format_command(
                command_template,
                input_path=input_path,
                output_path=output_path,
            )
            stdout, stderr, returncode = await _run_command(command)
            if returncode != 0:
                raise RuntimeError(
                    f"Local STT command failed with exit code {returncode}: {_decode_output(stderr).strip()}"
                )

            if "{output}" in command_template and output_path.exists():
                text = output_path.read_text(encoding="utf-8-sig").strip()
            else:
                text = _decode_output(stdout).strip()
            if not text:
                raise RuntimeError("Local STT command returned an empty transcription")
            return text

    async def synthesize(self, text: str) -> Path:
        command_template = config.VOICE_TTS_COMMAND
        if not command_template:
            raise RuntimeError("MK4_TTS_COMMAND is not configured")
        if "{output}" not in command_template:
            raise RuntimeError("MK4_TTS_COMMAND must contain {output}")
        clean_text = str(text or "").strip()
        if not clean_text:
            raise ValueError("TTS text is empty")
        if len(clean_text) > config.VOICE_MAX_TTS_CHARS:
            clean_text = clean_text[: config.VOICE_MAX_TTS_CHARS]

        handle = tempfile.NamedTemporaryFile(prefix="mk4-tts-", suffix=".wav", delete=False)
        handle.close()
        output_path = Path(handle.name)
        try:
            command = _format_command(command_template, output_path=output_path)
            stdout, stderr, returncode = await _run_command(command, stdin=clean_text.encode("utf-8"))
            if returncode != 0:
                raise RuntimeError(
                    f"Local TTS command failed with exit code {returncode}: {_decode_output(stderr).strip()}"
                )
            if not output_path.exists() or output_path.stat().st_size <= 44:
                preview = _decode_output(stdout).strip()
                raise RuntimeError(
                    "Local TTS command did not create a valid WAV file"
                    + (f": {preview}" if preview else "")
                )
            return output_path
        except Exception:
            output_path.unlink(missing_ok=True)
            raise


async def _run_command(command: str, *, stdin: bytes | None = None) -> tuple[bytes, bytes, int]:
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(config.WORKSPACE_ROOT),
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin),
            timeout=config.VOICE_COMMAND_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise TimeoutError(
            f"Local voice command timed out after {config.VOICE_COMMAND_TIMEOUT_SECONDS:.0f}s"
        )
    return stdout, stderr, int(process.returncode or 0)


def _format_command(
    template: str,
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> str:
    values = {
        "input": _quote_arg(input_path) if input_path is not None else "",
        "output": _quote_arg(output_path) if output_path is not None else "",
    }
    try:
        return template.format(**values)
    except KeyError as exc:
        raise RuntimeError(f"Unknown placeholder in local voice command: {exc}") from exc


def _quote_arg(path: Path) -> str:
    value = str(path)
    if os.name == "nt":
        import subprocess

        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def _decode_output(data: bytes) -> str:
    if not data:
        return ""
    encodings = ["utf-8", locale.getpreferredencoding(False)]
    if os.name == "nt":
        encodings.extend(["mbcs", "cp949"])
    seen: set[str] = set()
    for encoding in encodings:
        if not encoding:
            continue
        key = encoding.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")
