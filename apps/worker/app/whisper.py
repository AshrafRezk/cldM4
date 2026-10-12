"""mlx-whisper large-v3-turbo via exclusive-slot subprocess (Phase F / G)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from .errors import CloudiatorError

log = logging.getLogger("cloudiator.whisper")

DEFAULT_MODEL_NAME = "whisper-large-v3-turbo"
SUPPORTED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm", ".mp4"}
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def whisper_model_path(settings) -> str:
    path = getattr(settings, "whisper_model_path", None) or ""
    return path


def assert_whisper_ready(settings) -> str:
    """Refuse to start a download inside an HTTP request."""
    model = whisper_model_path(settings)
    if not model or not os.path.isdir(model):
        raise CloudiatorError(
            503,
            "not_supported",
            "WHISPER_MODEL_PATH is not a local directory. Download "
            "mlx-community/whisper-large-v3-turbo offline before enabling transcriptions.",
            error_type="server_error",
        )
    return model


def _suffix_for(filename: str | None, content_type: str | None) -> str:
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in SUPPORTED_AUDIO_SUFFIXES:
            return suffix
    if content_type:
        mapping = {
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/wave": ".wav",
            "audio/mpeg": ".mp3",
            "audio/mp3": ".mp3",
            "audio/mp4": ".m4a",
            "audio/m4a": ".m4a",
            "audio/ogg": ".ogg",
            "audio/flac": ".flac",
            "audio/webm": ".webm",
        }
        mapped = mapping.get(content_type.split(";")[0].strip().lower())
        if mapped:
            return mapped
    return ".wav"


async def transcribe_bytes(
    data: bytes,
    *,
    settings,
    scheduler,
    filename: str | None = None,
    content_type: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    if not data:
        raise CloudiatorError(400, "invalid_request_error", "file is empty.", param="file")
    if len(data) > MAX_AUDIO_BYTES:
        raise CloudiatorError(
            400,
            "invalid_request_error",
            f"Audio must be at most {MAX_AUDIO_BYTES} bytes.",
            param="file",
        )
    model = assert_whisper_ready(settings)
    suffix = _suffix_for(filename, content_type)
    lang = _normalize_language(language)

    async def run() -> dict[str, Any]:
        return await _run_cli(data, suffix=suffix, model=model, language=lang, scheduler=scheduler)

    return await scheduler.run_exclusive("whisper", run)


async def _run_cli(
    data: bytes,
    *,
    suffix: str,
    model: str,
    language: str | None,
    scheduler,
) -> dict[str, Any]:
    work = tempfile.mkdtemp(prefix="whisper-")
    audio_path = os.path.join(work, f"audio{suffix}")
    out_path = os.path.join(work, "out.json")
    proc: asyncio.subprocess.Process | None = None
    try:
        Path(audio_path).write_bytes(data)
        argv = [
            sys.executable,
            "-m",
            "app.whisper_cli",
            "--audio",
            audio_path,
            "--model",
            model,
            "--out",
            out_path,
        ]
        if language:
            argv.extend(["--language", language])
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        scheduler.subprocesses.register(proc)
        stdout, stderr = await proc.communicate()
        code = proc.returncode or 0
        if code != 0 or not os.path.isfile(out_path):
            detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
            log.warning("whisper_cli failed code=%s detail=%s", code, detail[:300])
            raise CloudiatorError(
                500,
                "internal_error",
                (detail.splitlines()[-1] if detail else "Whisper transcription failed.")[:300],
                error_type="server_error",
            )
        payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
        text = str(payload.get("text") or "").strip()
        return {
            "text": text,
            "language": payload.get("language") or language,
            "model": DEFAULT_MODEL_NAME,
        }
    finally:
        if proc is not None and proc.returncode is not None:
            scheduler.subprocesses.forget(proc)
        shutil.rmtree(work, ignore_errors=True)


def _normalize_language(value: str | None) -> str | None:
    if value is None or value == "" or value == "auto":
        return None
    raw = value.strip().lower().replace("_", "-")
    # BCP-47 → Whisper two-letter where obvious.
    if raw.startswith("ar"):
        return "ar"
    if raw.startswith("en"):
        return "en"
    if raw.startswith("fr"):
        return "fr"
    if len(raw) == 2:
        return raw
    if "-" in raw:
        return raw.split("-", 1)[0]
    return raw[:8]


__all__ = [
    "DEFAULT_MODEL_NAME",
    "MAX_AUDIO_BYTES",
    "assert_whisper_ready",
    "transcribe_bytes",
    "whisper_model_path",
]
