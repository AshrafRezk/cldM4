"""Local speech for the browser call. No vendor, no Metal.

TTS is macOS `say` (Majed for Arabic, Samantha for English), cached on disk
by text+voice: script prompts are static, so after the first call every prompt
is a file read.

STT is whisper.cpp on the **CPU** (`--no-gpu`). The GPU belongs to Gemma
(PLAN.md: one Metal model at a time); a CPU transcription of a short answer
never unloads chat. One transcription at a time: a second caller waits a
second rather than both being slow. Apple's recognizer is not used because it
only does English on-device; Arabic goes to Apple's servers.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path

log = logging.getLogger("cloudiator.voice.speech")

DEFAULT_VOICES = {"ar": "Majed", "en": "Samantha"}
SAY = "/usr/bin/say"
TTS_TIMEOUT = 30.0
STT_TIMEOUT = 45.0
MAX_UTTERANCE_SECONDS = 30

NOISE_TAGS = re.compile(r"\[[^\]]*\]|\([^)]*\)")

_stt_lock = asyncio.Semaphore(1)


class SpeechUnavailable(Exception):
    """The configured speech backend cannot run on this machine."""


def _lang(language: str | None) -> str:
    return (language or "en").split("-")[0].split("_")[0].lower()


def voice_for(language: str | None, local_voice: str | None) -> str | None:
    return local_voice or DEFAULT_VOICES.get(_lang(language))


async def _run(args: list[str], timeout: float) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise SpeechUnavailable(f"{Path(args[0]).name} timed out after {timeout:.0f}s")
    if proc.returncode != 0:
        raise SpeechUnavailable(
            f"{Path(args[0]).name} exited {proc.returncode}: {err.decode(errors='replace')[-300:]}"
        )
    return out


async def synthesize(text: str, *, language: str | None, local_voice: str | None, cache_dir: str) -> bytes:
    """AAC in an .m4a container; every current browser plays it."""
    voice = voice_for(language, local_voice)
    key = hashlib.sha256(f"{voice}\0{text}".encode()).hexdigest()[:32]
    cache = Path(os.path.expanduser(cache_dir))
    path = cache / f"{key}.m4a"
    if path.is_file():
        return path.read_bytes()
    if not os.path.exists(SAY):
        raise SpeechUnavailable("macOS `say` is not available")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        text_file = Path(tmp) / "text.txt"
        text_file.write_text(text, encoding="utf-8")
        out = Path(tmp) / "out.m4a"
        args = [SAY, "--file-format=m4af", "--data-format=aac", "-o", str(out), "-f", str(text_file)]
        if voice:
            args[1:1] = ["-v", voice]
        await _run(args, TTS_TIMEOUT)
        data = out.read_bytes()
    path.write_bytes(data)
    return data


async def synthesize_data_url(text: str, **kwargs) -> str:
    return "data:audio/mp4;base64," + base64.b64encode(await synthesize(text, **kwargs)).decode()


async def transcribe(audio: bytes, *, language: str | None, settings) -> str:
    if not audio:
        return ""
    binary = settings.whisper_cpp_bin
    model = os.path.expanduser(settings.whisper_model)
    if not binary or not os.path.exists(binary):
        raise SpeechUnavailable(f"whisper.cpp is not installed ({binary})")
    if not os.path.isfile(model):
        raise SpeechUnavailable(f"whisper model is missing ({model})")
    async with _stt_lock:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "in"
            raw.write_bytes(audio)
            wav = Path(tmp) / "in.wav"
            # Whatever the browser sent (WAV from the call page, webm/mp4 from
            # elsewhere) becomes 16 kHz mono PCM, capped in length.
            await _run(
                [settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-i", str(raw),
                 "-t", str(MAX_UTTERANCE_SECONDS), "-ar", "16000", "-ac", "1", "-f", "wav", str(wav)],
                20.0,
            )
            base = Path(tmp) / "out"
            await _run(
                [binary, "-m", model, "-f", str(wav), "-l", _lang(language),
                 "--no-gpu", "-t", str(settings.whisper_threads), "-nt", "-np",
                 "-otxt", "-of", str(base)],
                STT_TIMEOUT,
            )
            text_path = base.with_suffix(".txt")
            text = text_path.read_text(encoding="utf-8", errors="replace") if text_path.exists() else ""
    # whisper.cpp marks silence and noise as [BLANK_AUDIO], (music), etc.
    return " ".join(NOISE_TAGS.sub(" ", text).split())
