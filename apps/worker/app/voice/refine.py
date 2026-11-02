"""Hybrid recognition: talk with the fast model, commit what the accurate one heard.

During a call the live model (Whisper Small, ~1-3 s) keeps the conversation
moving. Each free-text answer's audio is kept for the length of the call. When
the call ends the session waits as "refining"; Whisper large-v2 (~6 s an
answer, too slow to talk with) hears those answers again in a helper process,
and the session becomes "ready_to_commit" with the better words. Salesforce
only ever collects ready sessions, so it never sees the live guess first.

Nothing is lost on failure: a missing model, a crash or a timeout releases the
session with the live answers. The kept audio is deleted once a call is
released. Only free-text answers are kept at all (never a menu choice or a
yes/no), a call that ends any other way (abandoned, or nothing to refine) has
its audio deleted within seconds, and anything else is swept after a day.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from . import speech
from .engine import VoiceEngine, clean_answer, free_text, refinable_answers

log = logging.getLogger("cloudiator.voice.refine")

HELPER = Path(__file__).with_name("egy_refine.py")
SAFE = re.compile(r"[^A-Za-z0-9_-]")
KEEP_SECONDS = 24 * 3600


class Refiner:
    def __init__(self, settings, engine: VoiceEngine) -> None:
        self.settings = settings
        self.engine = engine
        self.root = Path(settings.voice_refine_dir)
        self._task: asyncio.Task | None = None

    @property
    def enabled(self) -> bool:
        model = self.settings.voice_refine_model
        return bool(model) and os.path.isfile(os.path.join(model, "model.bin")) and os.path.isfile(
            self.settings.voicetut_python
        )

    def _dir(self, session_id: str) -> Path:
        return self.root / SAFE.sub("_", session_id)

    # During the call -------------------------------------------------------

    def keep(self, session: Mapping[str, Any], step: str, audio: bytes, heard: str) -> None:
        """Keep the answer's audio until the call is refined. The latest answer to a step wins."""
        if not (self.enabled and audio and heard.strip()):
            return
        step_def = next((s for s in session["definition"]["steps"] if s["key"] == step), None)
        if step_def is None or not free_text(step_def):
            return  # menu choices and yes/no answers are never heard again, so never kept
        folder = self._dir(session["id"])
        folder.mkdir(parents=True, exist_ok=True)
        name = SAFE.sub("_", step)
        (folder / f"{name}.audio").write_bytes(audio)
        (folder / f"{name}.json").write_text(json.dumps({"heard": heard}, ensure_ascii=False))

    # After the call --------------------------------------------------------

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever(), name="voice-refine")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def run_forever(self, interval: float = 3.0) -> None:
        swept = 0.0
        while True:
            try:
                await self.refine_waiting()
                self.tidy()
                if time.time() - swept > 3600:
                    self.sweep()
                    swept = time.time()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("voice refine loop failed")
            await asyncio.sleep(interval)

    async def refine_waiting(self) -> int:
        sessions = self.engine.store.sessions_with_status("refining")
        for session in sessions:
            await self.refine(session)
        return len(sessions)

    async def refine(self, session: dict[str, Any]) -> dict[str, str]:
        """Re-hear one finished call and release it. Returns {step: new answer}."""
        changed: dict[str, str] = {}
        answers = dict(session["answers"])
        turns = [dict(t) for t in session["turns"]]
        try:
            if self.enabled:
                heard = await self._hear(session, refinable_answers(session["definition"], answers))
                for step, (live, better) in heard.items():
                    if not better or better == live:
                        continue
                    answers[step] = clean_answer(better)
                    changed[step] = answers[step]
                    # The transcript says what the accurate model heard, and keeps the live guess.
                    for turn in reversed(turns):
                        if turn.get("role") == "caller" and turn.get("text") == live:
                            turn["live"], turn["text"] = live, better
                            break
        except Exception as exc:  # noqa: BLE001
            log.warning("voice session %s refine failed, using the live answers: %s",
                        session["id"], type(exc).__name__)
            answers, turns, changed = dict(session["answers"]), [dict(t) for t in session["turns"]], {}
        finally:
            commit = self.engine.commit_for(session, turns, answers)
            self.engine.store.update_session(
                session["id"], answers=answers, turns=turns, commit_doc=commit, status="ready_to_commit"
            )
            shutil.rmtree(self._dir(session["id"]), ignore_errors=True)
        log.info("voice session %s ready to commit (%d answers refined)", session["id"], len(changed))
        return changed

    async def _hear(self, session: Mapping[str, Any], steps: list[str]) -> dict[str, tuple[str, str]]:
        folder = self._dir(session["id"])
        kept = []
        for step in steps:
            name = SAFE.sub("_", step)
            audio, note = folder / f"{name}.audio", folder / f"{name}.json"
            if audio.is_file() and note.is_file():
                kept.append((step, audio, json.loads(note.read_text())["heard"]))
        if not kept:
            return {}
        out: dict[str, tuple[str, str]] = {}
        with tempfile.TemporaryDirectory() as tmp:
            jobs = []
            for index, (step, audio, heard) in enumerate(kept):
                wav = Path(tmp) / f"{index}.wav"
                await speech._run(
                    [self.settings.ffmpeg_bin, "-nostdin", "-loglevel", "error", "-i", str(audio),
                     "-t", str(speech.MAX_UTTERANCE_SECONDS), "-ar", "16000", "-ac", "1",
                     "-c:a", "pcm_s16le", "-f", "wav", str(wav)],
                    20.0,
                )
                if speech.speech_seconds(wav) >= speech.MIN_SPEECH_SECONDS:
                    jobs.append({"id": str(index), "wav": str(wav)})
            if not jobs:
                return {}
            (Path(tmp) / "jobs.json").write_text(json.dumps(jobs))
            lines = await self._run_helper(Path(tmp) / "jobs.json", 60 + 30 * len(jobs))
        for line in lines:
            index = int(line["id"])
            step, _audio, heard = kept[index]
            if line.get("text") is not None:
                out[step] = (heard, speech.clean_transcript(line["text"]))
        return out

    async def _run_helper(self, jobs: Path, timeout: float) -> list[dict[str, Any]]:
        proc = await asyncio.create_subprocess_exec(
            self.settings.voicetut_python, "-I", str(HELPER), self.settings.voice_refine_model,
            str(self.settings.voice_refine_threads), str(jobs),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            # The model has no tokenizer.json, so faster-whisper loads Whisper's
            # standard one (openai/whisper-tiny) from the local cache; never the network mid-call.
            env={**os.environ, "HF_HUB_OFFLINE": "1"},
            # Behind live calls: the next caller's answers must not wait on this.
            preexec_fn=(lambda: os.nice(10)) if sys.platform != "win32" else None,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        lines = []
        for raw in stdout.decode("utf-8", "replace").splitlines():
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if isinstance(item, dict) and "id" in item:
                lines.append(item)
        return lines

    def tidy(self) -> int:
        """Delete kept audio as soon as its call is over without needing it:
        abandoned, or finished with nothing to refine."""
        removed = 0
        if not self.root.is_dir():
            return 0
        for folder in self.root.iterdir():
            status = self.engine.store.session_status(folder.name) if folder.is_dir() else None
            if status is not None and status not in ("in_progress", "refining"):
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        return removed

    def sweep(self) -> int:
        """Audio from calls that never finished (the caller hung up) goes after a day."""
        removed = 0
        if not self.root.is_dir():
            return 0
        for folder in self.root.iterdir():
            if folder.is_dir() and time.time() - folder.stat().st_mtime > KEEP_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        return removed
