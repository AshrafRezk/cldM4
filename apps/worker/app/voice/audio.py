"""Where the caller's audio comes from, in order of preference.

1. **Recording** a person uploaded for that question and language (from
   Salesforce). Nothing sounds more natural, and a call center has staff.
2. **Rendered** when the script was published, by the configured engine:
   - **azure**: Microsoft neural voices (Egyptian Arabic ar-EG-Salma/Shakir,
     British English en-GB-Sonia/Ryan). Only the fixed line text is sent, once
     per publish; callers' audio never leaves the Mini.
   - **voicetut**: VoiceTut-TTS (Egyptian Arabic + English, Apache-2.0), slow,
     on the CPU in its own venv — never during a call, never on the GPU.
3. **Fallback**: macOS `say` (Majed / Samantha), instant, so a call never waits
   for a render that has not finished.

Rendered clips are content-addressed (engine, speaker, language, text), so a
republish only renders lines whose text changed, and switching engines never
plays a clip made by the other one.
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
from .pronounce import spoken
from .engine import (
    CONFIRM_AGAIN,
    FAIL_MESSAGES,
    back_text,
    confirm_text,
    find_persona,
    hold_text,
    languages_of,
    off_script_text,
    speak,
)

log = logging.getLogger("cloudiator.voice.audio")

ENGINE_VERSIONS = {"voicetut": "voicetut-v1", "azure": "azure-v1"}
VOICETUT_DEFAULT = "Hadeer"
# VoiceTut's built-in speakers, by voice. Used to keep a persona's gender when
# a line has to fall back to a macOS voice before its natural clip is ready.
VOICETUT_FEMALE = {"Hadeer", "Hanan", "Mariam", "Rana", "Sarah", "Yasmin", "Yara"}
VOICETUT_MALE = {"Ahmed", "Ali", "Hassan", "Karim", "Mahmoud", "Mohammed", "Mostafa",
                 "Ramy", "Shaker", "Tareq", "Yehia", "Youssef"}
# Installed macOS voices per (language, gender). There is no female Arabic
# system voice on the Mini, so that slot is empty on purpose: a female persona
# must never speak as Majed.
FALLBACK_VOICES = {("ar", "male"): "Majed", ("en", "male"): "Daniel",
                   ("en", "female"): "Samantha", ("ar", "female"): None}
AZURE_VOICE = re.compile(r"^([a-z]{2,3}-[A-Z]{2})-[A-Za-z]+(?:Multilingual)?Neural(?:HD)?$")
AZURE_REGION = re.compile(r"^[a-z0-9]{3,30}$")
RENDER_TIMEOUT_PER_LINE = 300.0
SAFE_PART = re.compile(r"[^A-Za-z0-9_.-]")


def _lang(language: str) -> str:
    return language.split("-")[0].lower()


def script_lines(script: Mapping[str, Any], speaker_for=None) -> list[dict[str, Any]]:
    """Every fixed line a caller can hear, per persona and language. With
    personas, `{{agent}}` is their name and each speaks in their own voice.
    `text` is what the caller's page shows; `spoken` (with harakat, see
    pronounce.py) is what the voice renders and what keys the rendered clip."""
    lines = []
    for persona in script.get("personas") or [None]:
        pid = persona["id"] if persona else None
        for language in languages_of(script):
            speaker = speaker_for(script, language, persona) if speaker_for else VOICETUT_DEFAULT
            base = {"language": language, "speaker": speaker, "persona": pid}
            for step in script["steps"]:
                lines.append({**base, "key": step["key"], "text": speak(step["say"], language, persona)})
            fail = (
                speak(script["fail_say"], language, persona)
                if script.get("fail_say")
                else FAIL_MESSAGES["ar" if _lang(language) == "ar" else "en"]
            )
            lines.append({**base, "key": "__fail__", "text": fail})
            lines.append({**base, "key": "__hold__", "text": speak(hold_text(script, language), language, persona)})
            lines.append({**base, "key": "__offscript__", "text": speak(off_script_text(script, language), language, persona)})
            if script.get("faq"):
                lines.append({**base, "key": "__back__", "text": speak(back_text(language), language, persona)})
            for item in script.get("faq") or []:
                lines.append({**base, "key": f"__faq_{item['key']}", "text": speak(item["say"], language, persona)})
            if any(step.get("confirm") for step in script["steps"]):
                # Digits are spoken as one live sentence (confirm_clip); only the
                # "say it again" line is fixed and pre-rendered.
                lang = "ar" if _lang(language) == "ar" else "en"
                lines.append({**base, "key": "__again__", "text": CONFIRM_AGAIN[lang]})
    for line in lines:
        line["spoken"] = spoken(line["text"], line["language"], script)
    return lines


class VoiceAudio:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.root = Path(os.path.expanduser(settings.voice_audio_dir))
        self.queue: asyncio.Queue[list[dict[str, str]]] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self.last_error: str | None = None

    # Engine and voices -------------------------------------------------------

    @property
    def engine(self) -> str:
        """auto: Azure when its key is set, else VoiceTut when installed, else off."""
        s = self.settings
        choice = (s.voice_tts_engine or "auto").lower()
        azure_ready = bool(s.azure_speech_key and s.azure_speech_region)
        voicetut_ready = os.path.exists(s.voicetut_python)
        if choice == "auto":
            return "azure" if azure_ready else "voicetut" if voicetut_ready else "say"
        if choice == "azure" and not azure_ready:
            return "say"
        if choice == "voicetut" and not voicetut_ready:
            return "say"
        return choice if choice in ENGINE_VERSIONS else "say"

    def speaker_for(self, script: Mapping[str, Any], language: str, persona: Mapping[str, Any] | None = None) -> str:
        chosen = ((persona or {}).get("voices") or script.get("voices") or {}).get(language) or ""
        if self.engine == "azure":
            if AZURE_VOICE.match(chosen):
                return chosen
            return self.settings.azure_voice_ar if _lang(language) == "ar" else self.settings.azure_voice_en
        return chosen if chosen and not AZURE_VOICE.match(chosen) else VOICETUT_DEFAULT

    def lines(self, script: Mapping[str, Any]) -> list[dict[str, str]]:
        return script_lines(script, self.speaker_for)

    # Paths -------------------------------------------------------------------

    def rendered_path(self, speaker: str, language: str, text: str, engine: str | None = None) -> Path:
        engine = engine or self.engine
        version = ENGINE_VERSIONS.get(engine, engine)
        digest = hashlib.sha256(f"{version}\0{speaker}\0{_lang(language)}\0{text}".encode()).hexdigest()
        suffix = ".mp3" if engine == "azure" else ".m4a"
        return self.root / "rendered" / f"{digest[:40]}{suffix}"

    def recording_path(
        self, tenant_id: str, script_id: str, key: str, language: str, persona: str | None = None
    ) -> Path:
        """One recording per line, language and persona: the real Mariam records Mariam's lines."""
        tenant = hashlib.sha256(tenant_id.encode()).hexdigest()[:16]
        who = f".{SAFE_PART.sub('_', persona)}" if persona else ""
        name = f"{SAFE_PART.sub('_', key)}.{SAFE_PART.sub('_', language)}{who}.m4a"
        return self.root / "recordings" / tenant / SAFE_PART.sub("_", script_id) / name

    # Call time ---------------------------------------------------------------

    async def clip(
        self,
        *,
        tenant_id: str,
        script: Mapping[str, Any],
        key: str | None,
        language: str,
        text: str,
        persona: str | None = None,
    ) -> tuple[str | None, str]:
        """(data URL, source) for one line. Never blocks on a render."""
        chosen = find_persona(script, persona) if script.get("personas") else None
        pid = chosen["id"] if chosen else None
        if key:
            recording = self.recording_path(tenant_id, script["id"], key, language, pid)
            if recording.is_file():
                return _data_url(recording.read_bytes()), "recording"
        if self.engine != "say":
            rendered = self.rendered_path(
                self.speaker_for(script, language, chosen), language, spoken(text, language, script)
            )
            if rendered.is_file():
                return _data_url(rendered.read_bytes(), rendered.suffix), "rendered"
        # Gender only binds when someone chose the voice (a persona, or the
        # script's voices); the engine's own default speaker does not.
        picked = ((chosen or {}).get("voices") or script.get("voices") or {}).get(language)
        gender = "female" if picked in VOICETUT_FEMALE else "male" if picked in VOICETUT_MALE else None
        local_voice = FALLBACK_VOICES.get((_lang(language), gender)) if gender else None
        if gender and local_voice is None:
            # Better silent (the page still shows the text) than the wrong person's voice.
            return None, "pending"
        try:
            data = await speech.synthesize(
                text, language=language, local_voice=local_voice, cache_dir=self.settings.voice_tts_cache
            )
            return _data_url(data), "fallback"
        except speech.SpeechUnavailable as exc:
            log.warning("tts unavailable: %s", exc)
            return None, "none"

    async def confirm_clip(
        self, *, tenant_id: str, script: Mapping[str, Any], language: str, persona: str | None, digits: str
    ) -> tuple[str | None, str]:
        """One grouped sentence in the persona's voice, cached by voice+digits."""
        return await self.live_clip(
            script=script, language=language, persona=persona, text=confirm_text(digits, language),
            cache_key=f"confirm:{digits}",
        )

    async def live_clip(
        self,
        *,
        script: Mapping[str, Any],
        language: str,
        persona: str | None,
        text: str,
        cache_key: str | None = None,
    ) -> tuple[str | None, str]:
        """Speak a dynamic line now (number read-back, knowledge answer).

        Azure neural when configured; otherwise macOS `say`. VoiceTut is never
        called on the live path (~20 s per line)."""
        chosen = find_persona(script, persona) if script.get("personas") else None
        speaker = self.speaker_for(script, language, chosen)
        cache = self.root / "live"
        cache.mkdir(parents=True, exist_ok=True)
        key = cache_key or text
        digest = hashlib.sha256(
            f"{self.engine}\0{speaker}\0{_lang(language)}\0{key}\0{text}".encode()
        ).hexdigest()[:40]
        if self.engine == "azure":
            path = cache / f"{digest}.mp3"
            if path.is_file():
                return _data_url(path.read_bytes(), ".mp3"), "rendered"
            try:
                audio = await azure_tts(spoken(text, language, script), speaker, self.settings)
            except speech.SpeechUnavailable as exc:
                log.warning("live azure tts unavailable: %s", exc)
                return await self._live_say(text, language, chosen, speaker, cache, digest)
            path.write_bytes(audio)
            return _data_url(audio, ".mp3"), "rendered"
        return await self._live_say(text, language, chosen, speaker, cache, digest)

    async def _live_say(
        self,
        text: str,
        language: str,
        persona: Mapping[str, Any] | None,
        speaker: str,
        cache: Path,
        digest: str,
    ) -> tuple[str | None, str]:
        path = cache / f"{digest}.m4a"
        if path.is_file():
            return _data_url(path.read_bytes()), "fallback"
        picked = ((persona or {}).get("voices") or {}).get(language) or speaker
        gender = "female" if picked in VOICETUT_FEMALE else "male" if picked in VOICETUT_MALE else None
        if AZURE_VOICE.match(picked or ""):
            gender = "female" if any(n in (picked or "") for n in ("Salma", "Sonia")) else \
                "male" if any(n in (picked or "") for n in ("Shakir", "Ryan")) else gender
        local_voice = FALLBACK_VOICES.get((_lang(language), gender)) if gender else None
        if gender and local_voice is None:
            local_voice = FALLBACK_VOICES.get((_lang(language), "male"))
        try:
            data = await speech.synthesize(
                text, language=language, local_voice=local_voice, cache_dir=self.settings.voice_tts_cache
            )
        except speech.SpeechUnavailable as exc:
            log.warning("live say unavailable: %s", exc)
            return None, "none"
        path.write_bytes(data)
        return _data_url(data), "fallback"

    # Recordings --------------------------------------------------------------

    async def save_recording(
        self, tenant_id: str, script_id: str, key: str, language: str, audio: bytes,
        persona: str | None = None,
    ) -> Path:
        path = self.recording_path(tenant_id, script_id, key, language, persona)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "in"
            raw.write_bytes(audio)
            out = Path(tmp) / "out.m4a"
            await speech._run(
                # Studio takes are laptop-mic recordings: cut rumble, drop the
                # silence before the first word, and level every line the same.
                [self.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-i", str(raw),
                 "-t", "60", "-ac", "1",
                 "-af", "highpass=f=80,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,"
                        "loudnorm=I=-16:TP=-1.5:LRA=11",
                 "-ar", "24000", "-c:a", "aac", "-b:a", "96k", str(out)],
                30.0,
            )
            path.write_bytes(out.read_bytes())
        return path

    def delete_recording(
        self, tenant_id: str, script_id: str, key: str, language: str, persona: str | None = None
    ) -> bool:
        path = self.recording_path(tenant_id, script_id, key, language, persona)
        if path.is_file():
            path.unlink()
            return True
        return False

    def status(self, tenant_id: str, script: Mapping[str, Any]) -> list[dict[str, str]]:
        rows = []
        for line in self.lines(script):
            if self.recording_path(
                tenant_id, script["id"], line["key"], line["language"], line.get("persona")
            ).is_file():
                source = "recording"
            elif self.engine != "say" and self.rendered_path(
                line["speaker"], line["language"], line["spoken"]
            ).is_file():
                source = "rendered"
            else:
                source = "fallback"
            rows.append({"key": line["key"], "language": line["language"], "persona": line.get("persona"),
                         "speaker": line["speaker"], "source": source})
        return rows

    def readiness(self, tenant_id: str, script: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Per persona+language: how many lines have a natural voice (a person's
        recording or a render). Only fully ready ones take calls; with no render
        engine at all, the macOS voice is all there is, so everything is ready."""
        totals: dict[tuple, list[int]] = {}
        for row in self.status(tenant_id, script):
            key = (row.get("persona"), row["language"])
            counts = totals.setdefault(key, [0, 0])
            counts[1] += 1
            if row["source"] in ("recording", "rendered"):
                counts[0] += 1
        always = self.engine == "say"
        return [
            {"persona": persona, "language": language, "ready": done, "total": total,
             "ok": always or done == total}
            for (persona, language), (done, total) in totals.items()
        ]

    # Background rendering ----------------------------------------------------

    def enabled(self) -> bool:
        return self.engine != "say"

    def schedule(self, script: Mapping[str, Any]) -> int:
        """Queue the lines that have no clip yet. Returns how many."""
        if not self.enabled():
            return 0
        # One persona+language at a time, in call order: calls open per
        # persona+language only once all of its lines are natural (readiness),
        # so finishing Mariam-Arabic first beats a little of everyone.
        order = {step["key"]: i for i, step in enumerate(script["steps"])}
        order["__hold__"] = 1.5
        people = {p["id"]: i for i, p in enumerate(script.get("personas") or [])}
        langs = {lang: i for i, lang in enumerate(languages_of(script))}
        missing = sorted(
            (line for line in self.lines(script)
             if not self.rendered_path(line["speaker"], line["language"], line["spoken"]).is_file()),
            key=lambda line: (people.get(line.get("persona"), 0), langs.get(line["language"], 0),
                              order.get(line["key"], 99)),
        )
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
            pending = [l for l in batch if not self.rendered_path(l["speaker"], l["language"], l["spoken"]).is_file()]
            if pending:
                try:
                    await self._render(pending)
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001
                    self.last_error = str(exc)[:300]
                    log.error("voice render failed: %s", exc)

    async def _render(self, lines: Iterable[dict[str, str]]) -> None:
        if self.engine == "azure":
            await self._render_azure(list(lines))
        else:
            await self._render_voicetut(list(lines))

    async def _render_azure(self, lines: list[dict[str, str]]) -> None:
        """Seconds per line. Two requests at a time is well inside the free tier's limits."""
        gate = asyncio.Semaphore(2)
        done = 0
        errors: list[str] = []

        async def one(line: dict[str, str]) -> None:
            nonlocal done
            async with gate:
                try:
                    audio = await azure_tts(line["spoken"], line["speaker"], self.settings)
                except speech.SpeechUnavailable as exc:
                    errors.append(str(exc))
                    return
            target = self.rendered_path(line["speaker"], line["language"], line["spoken"], "azure")
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_suffix(".part")
            part.write_bytes(audio)
            part.replace(target)
            done += 1

        await asyncio.gather(*(one(line) for line in lines))
        log.info("voice render (azure): %d/%d lines", done, len(lines))
        if errors:
            raise speech.SpeechUnavailable(errors[0])

    async def _render_voicetut(self, lines: Iterable[dict[str, str]]) -> None:
        """One subprocess per batch: the model loads once, renders every line,
        and exits, so its ~3 GB never stays resident next to Gemma."""
        lines = list(lines)
        script = Path(__file__).with_name("voicetut_render.py")
        with tempfile.TemporaryDirectory() as tmp:
            jobs = [
                {"text": l["spoken"], "language": _lang(l["language"]), "speaker": l["speaker"],
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
            done = 0

            async def publish(index: int) -> None:
                nonlocal done
                line, wav = lines[index], Path(jobs[index]["wav"])
                if not wav.is_file():
                    return
                target = self.rendered_path(line["speaker"], line["language"], line["spoken"], "voicetut")
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp_out = target.with_suffix(".part.m4a")
                await speech._run(
                    [self.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-y", "-i", str(wav),
                     "-ac", "1", "-c:a", "aac", "-b:a", "64k", str(tmp_out)],
                    60.0,
                )
                tmp_out.replace(target)
                done += 1

            async def follow() -> None:
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    parts = raw.decode(errors="replace").split()
                    if len(parts) == 2 and parts[0] == "done" and parts[1].isdigit():
                        await publish(int(parts[1]))

            stderr_task = asyncio.create_task(proc.stderr.read())  # type: ignore[union-attr]
            try:
                await asyncio.wait_for(follow(), RENDER_TIMEOUT_PER_LINE * len(jobs) + 300)
                await proc.wait()
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise speech.SpeechUnavailable("VoiceTut render timed out")
            err = await stderr_task
            if proc.returncode != 0 and done == 0:
                raise speech.SpeechUnavailable(err.decode(errors="replace")[-400:])
            log.info("voice render: %d/%d lines", done, len(lines))


def _data_url(data: bytes, suffix: str = ".m4a") -> str:
    mime = "audio/mpeg" if suffix == ".mp3" else "audio/mp4"
    return f"data:{mime};base64," + base64.b64encode(data).decode()


async def azure_tts(text: str, voice: str, settings) -> bytes:
    """One line through Azure neural TTS. The host comes from the configured
    region only, never from a script, so a script cannot point this anywhere."""
    import httpx
    from xml.sax.saxutils import escape

    region = settings.azure_speech_region or ""
    if not AZURE_REGION.match(region):
        raise speech.SpeechUnavailable("AZURE_SPEECH_REGION is not a region name (e.g. westeurope)")
    match = AZURE_VOICE.match(voice)
    if not match:
        raise speech.SpeechUnavailable(f"{voice!r} is not an Azure neural voice name")
    ssml = (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{match.group(1)}">'
        f'<voice name="{voice}">{escape(text)}</voice></speak>'
    )
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                content=ssml.encode("utf-8"),
                headers={
                    "Ocp-Apim-Subscription-Key": settings.azure_speech_key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-48khz-96kbitrate-mono-mp3",
                    "User-Agent": "cloudiator-voice",
                },
            )
    except httpx.HTTPError as exc:
        raise speech.SpeechUnavailable(f"Azure TTS unreachable: {type(exc).__name__}") from exc
    if response.status_code != 200 or not response.content:
        raise speech.SpeechUnavailable(f"Azure TTS returned {response.status_code} for {voice}")
    return response.content
