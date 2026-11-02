"""Where the caller's audio comes from, in order of preference.

1. **Recording** a person uploaded for that question and language (from
   Salesforce). Nothing sounds more natural, and a call center has staff.
2. **Rendered**: VoiceTut-TTS (Egyptian Arabic + English, Apache-2.0) made the
   clip when the script was published. Script lines are fixed, so a slow,
   natural model runs once, in the background, on the CPU — never during a
   call and never on the Metal GPU that belongs to Gemma.
3. **Fallback**: macOS `say` (Majed / Samantha), instant, so a call never waits
   for a render that has not finished.

Rendered clips are content-addressed (engine, speaker, language, text), so a
republish only renders lines whose text changed.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import speech
from .engine import FAIL_MESSAGES, languages_of, text_for

log = logging.getLogger("cloudiator.voice.audio")

RENDER_ENGINE = "voicetut-v1"
DEFAULT_SPEAKERS = {"ar": "Hadeer", "en": "Hadeer"}
RENDER_TIMEOUT_PER_LINE = 300.0
SAFE_PART = re.compile(r"[^A-Za-z0-9_.-]")


def _lang(language: str) -> str:
    return language.split("-")[0].lower()


def script_lines(script: Mapping[str, Any]) -> list[dict[str, str]]:
    """Every fixed line a caller can hear, per language."""
    lines = []
    for language in languages_of(script):
        speaker = (script.get("voices") or {}).get(language) or DEFAULT_SPEAKERS.get(_lang(language), "Hadeer")
        for step in script["steps"]:
            lines.append(
                {"key": step["key"], "language": language, "speaker": speaker,
                 "text": text_for(step["say"], language)}
            )
        fail = (
            text_for(script["fail_say"], language)
            if script.get("fail_say")
            else FAIL_MESSAGES["ar" if _lang(language) == "ar" else "en"]
        )
        lines.append({"key": "__fail__", "language": language, "speaker": speaker, "text": fail})
    return lines


class VoiceAudio:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.root = Path(os.path.expanduser(settings.voice_audio_dir))
        self.queue: asyncio.Queue[list[dict[str, str]]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self.last_error: str | None = None

    # Paths -------------------------------------------------------------------

    def rendered_path(self, speaker: str, language: str, text: str) -> Path:
        digest = hashlib.sha256(f"{RENDER_ENGINE}\0{speaker}\0{_lang(language)}\0{text}".encode()).hexdigest()
        return self.root / "rendered" / f"{digest[:40]}.m4a"

    def recording_path(self, tenant_id: str, script_id: str, key: str, language: str) -> Path:
        tenant = hashlib.sha256(tenant_id.encode()).hexdigest()[:16]
        name = f"{SAFE_PART.sub('_', key)}.{SAFE_PART.sub('_', language)}.m4a"
        return self.root / "recordings" / tenant / SAFE_PART.sub("_", script_id) / name

    # Call time ---------------------------------------------------------------

    async def clip(
        self, *, tenant_id: str, script: Mapping[str, Any], key: str | None, language: str, text: str
    ) -> tuple[str | None, str]:
        """(data URL, source) for one line. Never blocks on a render."""
        if key:
            recording = self.recording_path(tenant_id, script["id"], key, language)
            if recording.is_file():
                return _data_url(recording.read_bytes()), "recording"
        speaker = (script.get("voices") or {}).get(language) or DEFAULT_SPEAKERS.get(_lang(language), "Hadeer")
        rendered = self.rendered_path(speaker, language, text)
        if rendered.is_file():
            return _data_url(rendered.read_bytes()), "rendered"
        try:
            data = await speech.synthesize(
                text, language=language, local_voice=None, cache_dir=self.settings.voice_tts_cache
            )
            return _data_url(data), "fallback"
        except speech.SpeechUnavailable as exc:
            log.warning("tts unavailable: %s", exc)
            return None, "none"

    # Recordings --------------------------------------------------------------

    async def save_recording(
        self, tenant_id: str, script_id: str, key: str, language: str, audio: bytes
    ) -> Path:
        path = self.recording_path(tenant_id, script_id, key, language)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "in"
            raw.write_bytes(audio)
            out = Path(tmp) / "out.m4a"
            await speech._run(
                [self.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-i", str(raw),
                 "-t", "60", "-ac", "1", "-ar", "24000", "-c:a", "aac", "-b:a", "64k", str(out)],
                30.0,
            )
            path.write_bytes(out.read_bytes())
        return path

    def delete_recording(self, tenant_id: str, script_id: str, key: str, language: str) -> bool:
        path = self.recording_path(tenant_id, script_id, key, language)
        if path.is_file():
            path.unlink()
            return True
        return False

    def status(self, tenant_id: str, script: Mapping[str, Any]) -> list[dict[str, str]]:
        rows = []
        for line in script_lines(script):
            if self.recording_path(tenant_id, script["id"], line["key"], line["language"]).is_file():
                source = "recording"
            elif self.rendered_path(line["speaker"], line["language"], line["text"]).is_file():
                source = "rendered"
            else:
                source = "fallback"
            rows.append({"key": line["key"], "language": line["language"], "speaker": line["speaker"],
                         "source": source})
        return rows

    # Background rendering ----------------------------------------------------

    def enabled(self) -> bool:
        return (
            self.settings.voice_tts_engine == "voicetut"
            and os.path.exists(self.settings.voicetut_python)
        )

    def schedule(self, script: Mapping[str, Any]) -> int:
        """Queue the lines that have no clip yet. Returns how many."""
        if not self.enabled():
            return 0
        missing = [
            line for line in script_lines(script)
            if not self.rendered_path(line["speaker"], line["language"], line["text"]).is_file()
        ]
        if missing:
            self.queue.put_nowait(missing)
            self._ensure_worker()
        return len(missing)

    def _ensure_worker(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="voice-render")

    async def _run(self) -> None:
        while not self.queue.empty():
            batch = self.queue.get_nowait()
            pending = [l for l in batch if not self.rendered_path(l["speaker"], l["language"], l["text"]).is_file()]
            if pending:
                try:
                    await self._render(pending)
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001
                    self.last_error = str(exc)[:300]
                    log.error("voice render failed: %s", exc)

    async def _render(self, lines: Iterable[dict[str, str]]) -> None:
        """One subprocess per batch: the model loads once, renders every line,
        and exits, so its ~3 GB never stays resident next to Gemma."""
        lines = list(lines)
        script = Path(__file__).with_name("voicetut_render.py")
        with tempfile.TemporaryDirectory() as tmp:
            jobs = [
                {"text": l["text"], "language": _lang(l["language"]), "speaker": l["speaker"],
                 "wav": str(Path(tmp) / f"{i}.wav")}
                for i, l in enumerate(lines)
            ]
            (Path(tmp) / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/nice", "-n", "10", self.settings.voicetut_python, "-I", str(script),
                str(Path(tmp) / "jobs.json"), str(self.settings.voicetut_threads),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _out, err = await asyncio.wait_for(
                    proc.communicate(), RENDER_TIMEOUT_PER_LINE * len(jobs) + 300
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise speech.SpeechUnavailable("VoiceTut render timed out")
            if proc.returncode != 0:
                raise speech.SpeechUnavailable(err.decode(errors="replace")[-400:])
            done = 0
            for line, job in zip(lines, jobs):
                wav = Path(job["wav"])
                if not wav.is_file():
                    continue
                target = self.rendered_path(line["speaker"], line["language"], line["text"])
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp_out = target.with_suffix(".part.m4a")
                await speech._run(
                    [self.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-y", "-i", str(wav),
                     "-ac", "1", "-c:a", "aac", "-b:a", "64k", str(tmp_out)],
                    60.0,
                )
                tmp_out.replace(target)
                done += 1
            log.info("voice render: %d/%d lines", done, len(lines))


def _data_url(data: bytes) -> str:
    return "data:audio/mp4;base64," + base64.b64encode(data).decode()
